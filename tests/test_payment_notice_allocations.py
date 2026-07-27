from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.contact import Contact, ContactGroup
from app.models.group_message import GroupMessage
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.services.payment_service import PaymentService
from app.services.payment_tracking_service import PaymentTrackingService
from app.services.business_application_service import BusinessApplicationService
from app.services.reminder_service import ReminderService
from app.utils.datetime_utils import now_tz


def _case(db_session) -> LegalCase:
    legal_case = LegalCase(
        case_no="(2026)闽0625民初1658号",
        debtor_name="黄建勇",
        plaintiff_name="测试科技有限公司",
        group_id="payment-allocation-group",
        due_date=now_tz().date() + timedelta(days=30),
        total_amount=Decimal("5000.00"),
        paid_amount=Decimal("0.00"),
        status="normal",
    )
    db_session.add(legal_case)
    db_session.flush()
    return legal_case


def _notice(db_session, legal_case: LegalCase, amount: str, text: str) -> LegalEvent:
    event = LegalEvent(
        case_id=legal_case.id,
        event_type="payment_notice",
        amount=Decimal(amount),
        extracted_text=text,
        attribution_status="confirmed",
        business_status="applied",
    )
    db_session.add(event)
    db_session.flush()
    return event


def test_two_notices_in_one_case_keep_independent_payment_state(db_session):
    legal_case = _case(db_session)
    first = _notice(db_session, legal_case, "100.00", "诉讼费100元")
    second = _notice(db_session, legal_case, "200.00", "公告费200元")

    record, created = PaymentService(db_session).create(
        legal_case,
        amount=Decimal("100.00"),
        record_type="fee_payment",
        status="approved",
        fingerprint="fee-payment-first",
    )

    assert created is True
    assert record.applies_to_event_id == first.id
    assert legal_case.paid_amount == Decimal("0.00")
    _, rows = PaymentTrackingService(db_session).list_rows()
    by_event = {row["event_id"]: row for row in rows}
    assert by_event[first.id]["payment_status"] == "paid"
    assert by_event[first.id]["paid_amount"] == Decimal("100.00")
    assert by_event[second.id]["payment_status"] == "pending"
    assert by_event[second.id]["paid_amount"] == Decimal("0.00")


def test_ambiguous_equal_amount_receipt_remains_unassigned(db_session):
    legal_case = _case(db_session)
    _notice(db_session, legal_case, "100.00", "诉讼费100元")
    _notice(db_session, legal_case, "100.00", "公告费100元")

    record, _ = PaymentService(db_session).create(
        legal_case,
        amount=Decimal("100.00"),
        record_type="fee_payment",
        status="approved",
        fingerprint="ambiguous-fee-payment",
    )

    assert record.applies_to_event_id is None
    total, receipts = PaymentTrackingService(db_session).list_unassigned_receipts()
    assert total == 1
    assert receipts[0]["id"] == record.id


def test_manual_assignment_reclassifies_repayment_without_inflating_case_paid_amount(db_session, monkeypatch):
    legal_case = _case(db_session)
    notice = _notice(db_session, legal_case, "100.00", "诉讼费100元")
    record, _ = PaymentService(db_session).create(
        legal_case,
        amount=Decimal("100.00"),
        record_type="repayment",
        status="approved",
        fingerprint="manual-reclassify",
    )
    assert legal_case.paid_amount == Decimal("100.00")
    monkeypatch.setattr(PaymentService, "_sync_notice_payment", lambda *_args: None)

    PaymentService(db_session).assign_to_notice(record, notice.id, "tester")

    assert record.record_type == "fee_payment"
    assert record.applies_to_event_id == notice.id
    assert legal_case.paid_amount == Decimal("0.00")


def test_fee_reversal_restores_future_notice_reminders(db_session, monkeypatch):
    legal_case = _case(db_session)
    notice = _notice(db_session, legal_case, "100.00", "诉讼费100元")
    reminder = Reminder(
        case_id=legal_case.id,
        group_id=legal_case.group_id,
        reminder_type="payment_tracking",
        remind_at=now_tz() + timedelta(days=3),
        content="请缴纳诉讼费",
        source_event_id=notice.id,
        status="pending",
    )
    confirmation_reminder = Reminder(
        case_id=legal_case.id,
        group_id=legal_case.group_id,
        reminder_type="payment_confirmation",
        remind_at=now_tz() + timedelta(minutes=90),
        content="请确认是否缴费",
        source_event_id=notice.id,
        status="pending",
    )
    db_session.add_all([reminder, confirmation_reminder])
    record, _ = PaymentService(db_session).create(
        legal_case,
        amount=Decimal("100.00"),
        record_type="fee_payment",
        applies_to_event_id=notice.id,
        status="approved",
        fingerprint="reversible-fee-payment",
    )
    assert reminder.status == "cancelled"
    assert confirmation_reminder.status == "cancelled"
    monkeypatch.setattr(PaymentService, "_sync_notice_payment", lambda *_args: None)

    reversal = PaymentService(db_session).reverse(record, "tester", "凭证录入错误")

    assert reversal.record_type == "fee_reversal"
    assert reminder.status == "pending"
    assert reminder.cancel_reason is None
    assert confirmation_reminder.status == "pending"
    assert confirmation_reminder.cancel_reason is None
    assert db_session.scalar(select(PaymentRecord).where(PaymentRecord.reversal_of_id == record.id)) is reversal


def test_manual_assignment_api_links_receipt_to_selected_notice(client, db_session, monkeypatch):
    legal_case = _case(db_session)
    first = _notice(db_session, legal_case, "100.00", "诉讼费100元")
    second = _notice(db_session, legal_case, "100.00", "公告费100元")
    record, _ = PaymentService(db_session).create(
        legal_case,
        amount=Decimal("100.00"),
        record_type="fee_payment",
        status="approved",
        fingerprint="api-manual-assignment",
    )
    db_session.commit()
    assert record.applies_to_event_id is None
    monkeypatch.setattr(PaymentService, "_sync_notice_payment", lambda *_args: None)

    response = client.post(
        f"/api/v1/legal/payment-trackings/{second.id}/assign-receipt",
        json={"payment_id": record.id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["applies_to_event_id"] == second.id
    db_session.expire_all()
    assert db_session.get(PaymentRecord, record.id).applies_to_event_id == second.id
    assert PaymentTrackingService(db_session).get_row(first.id)["payment_status"] == "pending"
    assert PaymentTrackingService(db_session).get_row(second.id)["payment_status"] == "paid"


def test_payment_notice_creates_30_and_90_minute_confirmation_followups(db_session):
    legal_case = _case(db_session)
    legal_case.debtor_wecom_userid = "merchant-user-001"
    notice = _notice(db_session, legal_case, "25.00", "案件受理费25元")
    started_at = now_tz()

    reminders = ReminderService(db_session).create_payment_confirmation_followups(
        legal_case.id,
        source_event_id=notice.id,
        start_at=started_at,
        payment_type="案件受理费",
        payment_amount=notice.amount,
    )

    assert len(reminders) == 2
    assert {round((item.remind_at - started_at).total_seconds() / 60) for item in reminders} == {30, 90}
    assert {item.target_userid for item in reminders} == {"merchant-user-001"}
    assert all("已缴费/已代缴/已收款" in item.content for item in reminders)


def test_payment_reminders_return_to_source_group_and_mention_source_sender(db_session):
    legal_case = _case(db_session)
    legal_case.group_id = "case-primary-group"
    legal_case.debtor_wecom_userid = "case-debtor"
    legal_case.lawyer_wecom_userid = "case-lawyer"
    message = GroupMessage(
        group_id="payment-source-group",
        sender_id="archive-sender",
        msg_type="text",
        content="案件受理费25元，请安排缴费",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    contact = Contact(
        display_name="原消息发送人",
        archive_user_id="archive-sender",
        wecomapi_user_id="wecomapi-sender",
        source="test",
    )
    db_session.add_all([message, contact])
    db_session.flush()
    db_session.add(ContactGroup(contact_id=contact.id, group_id=message.group_id, membership_status="observed"))
    notice = LegalEvent(
        case_id=legal_case.id,
        group_message_id=message.id,
        event_type="payment_notice",
        event_time=message.received_at,
        amount=Decimal("25.00"),
        extracted_text=message.content,
        attribution_status="confirmed",
        business_status="approved",
        approved_by="tester",
    )
    db_session.add(notice)
    db_session.flush()

    BusinessApplicationService(db_session).apply_event(notice.id)

    reminders = list(
        db_session.scalars(select(Reminder).where(Reminder.source_event_id == notice.id)).all()
    )
    assert len(reminders) == 5
    assert {item.group_id for item in reminders} == {"payment-source-group"}
    assert {item.target_userid for item in reminders} == {"wecomapi-sender"}
    assert {item.reminder_type for item in reminders} == {"payment_confirmation", "payment_tracking"}


def test_source_sender_id_is_used_when_contact_mapping_is_missing(db_session):
    legal_case = _case(db_session)
    message = GroupMessage(
        group_id="payment-source-group",
        sender_id="source-sender-id",
        msg_type="text",
        content="公告费400元",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    notice = LegalEvent(
        case_id=legal_case.id,
        group_message_id=None,
        event_type="payment_notice",
        attribution_status="confirmed",
        business_status="approved",
    )
    db_session.add_all([message, notice])
    db_session.flush()
    notice.group_message_id = message.id

    group_id, target_userid = PaymentTrackingService(db_session).reminder_destination(notice, legal_case)

    assert group_id == "payment-source-group"
    assert target_userid == "source-sender-id"


def test_explicit_text_confirmation_closes_single_open_notice(db_session):
    legal_case = _case(db_session)
    notice = _notice(db_session, legal_case, "25.00", "案件受理费25元")
    reminders = ReminderService(db_session).create_payment_confirmation_followups(
        legal_case.id,
        source_event_id=notice.id,
        start_at=now_tz(),
        payment_type="案件受理费",
        payment_amount=notice.amount,
    )
    confirmation = LegalEvent(
        case_id=legal_case.id,
        event_type="payment_screenshot",
        extracted_text="已代缴",
        attribution_status="confirmed",
        business_status="approved",
        approved_by="tester",
    )
    db_session.add(confirmation)
    db_session.flush()

    BusinessApplicationService(db_session).apply_event(confirmation.id)

    record = db_session.scalar(select(PaymentRecord).where(PaymentRecord.source_event_id == confirmation.id))
    assert record is not None
    assert record.amount == Decimal("25.00")
    assert record.applies_to_event_id == notice.id
    assert all(item.status == "cancelled" for item in reminders)


def test_confirmation_without_amount_or_unique_notice_is_not_silently_applied(db_session):
    legal_case = _case(db_session)
    _notice(db_session, legal_case, "25.00", "案件受理费25元")
    _notice(db_session, legal_case, "400.00", "公告费400元")
    confirmation = LegalEvent(
        case_id=legal_case.id,
        event_type="payment_screenshot",
        extracted_text="已缴费",
        attribution_status="confirmed",
        business_status="approved",
        approved_by="tester",
    )
    db_session.add(confirmation)
    db_session.flush()

    with pytest.raises(ValueError, match="缺少金额"):
        BusinessApplicationService(db_session).apply_event(confirmation.id)

    assert confirmation.business_status == "approved"


def test_daily_summary_groups_confirmed_and_pending_notices(client, db_session):
    legal_case = _case(db_session)
    message = GroupMessage(
        group_id=legal_case.group_id,
        sender_id="legal-user-001",
        msg_type="text",
        content="案件受理费25元",
        raw_payload_json="{}",
        received_at=now_tz(),
    )
    db_session.add(message)
    db_session.flush()
    paid_notice = _notice(db_session, legal_case, "25.00", "案件受理费25元")
    paid_notice.group_message_id = message.id
    _notice(db_session, legal_case, "400.00", "公告费400元")
    PaymentService(db_session).create(
        legal_case,
        amount=Decimal("25.00"),
        record_type="fee_payment",
        applies_to_event_id=paid_notice.id,
        status="approved",
        fingerprint="daily-summary-paid",
    )
    db_session.commit()

    response = client.get(f"/api/v1/legal/payment-trackings/daily-summary?date={now_tz().date().isoformat()}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["confirmed_count"] == 1
    assert data["pending_count"] == 1
    assert "一、已确认收款/已缴费" in data["content"]
    assert "二、待确认/未支付的缴费" in data["content"]
    assert "案件受理费25.00元" in data["content"]
