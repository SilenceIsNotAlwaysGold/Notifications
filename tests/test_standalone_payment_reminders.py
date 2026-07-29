import json
from datetime import timedelta

from sqlalchemy import select

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.models.business_outbox import BusinessOutbox
from app.schemas.legal import MockMessageCreate
from app.services.message_service import MessageService
from app.utils.datetime_utils import now_tz


GROUP_ID = "standalone-payment-group"


def _send(db_session, content: str, sender: str = "notice-sender", minutes: int = 0):
    return MessageService(db_session).handle_incoming_message(
        MockMessageCreate(
            group_id=GROUP_ID,
            sender_id=sender,
            msg_type="text",
            content=content,
            received_at=now_tz() + timedelta(minutes=minutes),
        )
    )


def _reminders(db_session):
    return list(db_session.scalars(select(Reminder).order_by(Reminder.id)).all())


def test_unassigned_payment_notice_creates_source_group_followups_only(db_session):
    result = _send(
        db_session,
        "李江胜，案号：（2026）桂 0702 民初 5834 号，案件受理费 25 元，26.8.2之前缴费",
    )

    event = db_session.get(LegalEvent, result["event_ids"][0])
    reminders = _reminders(db_session)
    assert result["case_id"] is None
    assert event.event_type == "payment_notice"
    assert event.case_id is None
    assert event.attribution_status == "not_required"
    assert len(reminders) == 2
    assert {item.group_id for item in reminders} == {GROUP_ID}
    assert {item.target_userid for item in reminders} == {"notice-sender"}
    assert {round((item.remind_at - event.group_message.received_at).total_seconds() / 60) for item in reminders} == {30, 90}
    assert all("李江胜" in item.content and "案件受理费" in item.content for item in reminders)
    assert db_session.scalar(select(LegalCase.id)) is None
    assert db_session.scalar(select(PaymentRecord.id)) is None
    assert db_session.scalar(select(BusinessOutbox.id)) is None


def test_confirmation_by_any_group_member_closes_standalone_notice(db_session):
    _send(db_session, "李江胜，案号：（2026）桂0702民初5834号，案件受理费25元，请缴费")

    _send(db_session, "李江胜，我已交诉讼费。", sender="another-group-member", minutes=10)

    reminders = _reminders(db_session)
    assert len(reminders) == 2
    assert all(item.status == "cancelled" for item in reminders)
    assert all("明确确认缴费" in (item.cancel_reason or "") for item in reminders)
    assert db_session.scalar(select(PaymentRecord.id)) is None


def test_quoted_payment_confirmation_closes_original_notice_without_creating_followups(db_session):
    original = "李立迁，案号：（2026）冀0109民初7702号，案件受理费25元，请缴费"
    notice = _send(db_session, original)

    result = _send(
        db_session,
        "这是一条引用/回复消息：\n"
        f'“法务调解 森：\n@致和法务-钧 【缴费待确认】{original}。请付款后回复“已缴费/已代缴/已收款”。”\n'
        "------\n"
        "这个被告的诉讼费已代缴",
        sender="ShanShan",
        minutes=10,
    )

    original_reminders = list(
        db_session.scalars(select(Reminder).where(Reminder.source_event_id == notice["event_ids"][0])).all()
    )
    assert all(item.status == "cancelled" for item in original_reminders)
    assert len(_reminders(db_session)) == 2
    assert result["reminder_ids"] == [item.id for item in original_reminders]
    confirmation = db_session.get(LegalEvent, result["event_ids"][0])
    assert confirmation.event_type == "payment_screenshot"


def test_quoted_payment_reminder_with_non_confirmation_reply_does_not_create_or_close_notice(db_session):
    original = "李立迁，案号：（2026）冀0109民初7702号，案件受理费25元，请缴费"
    notice = _send(db_session, original)

    result = _send(
        db_session,
        "这是一条引用/回复消息：\n"
        f'“法务调解 森：\n@致和法务-钧 【缴费待确认】{original}。请付款后回复“已缴费/已代缴/已收款”。”\n'
        "------\n"
        "稍等，我核实一下",
        sender="ShanShan",
        minutes=10,
    )

    original_reminders = list(
        db_session.scalars(select(Reminder).where(Reminder.source_event_id == notice["event_ids"][0])).all()
    )
    assert {item.status for item in original_reminders} == {"pending"}
    assert len(_reminders(db_session)) == 2
    assert result["reminder_ids"] == []
    assert result["event_ids"] == []


def test_late_confirmation_records_payment_after_all_followups_were_sent(db_session):
    notice = _send(db_session, "李立迁，案号：（2026）冀0109民初7702号，案件受理费25元，请缴费")
    reminders = _reminders(db_session)
    for reminder in reminders:
        reminder.status = "sent"
        reminder.sent_at = reminder.remind_at

    result = _send(
        db_session,
        "这是一条引用/回复消息：\n"
        "“法务调解 森：\n@致和法务-钧 【缴费待确认】李立迁，案号：（2026）冀0109民初7702号，案件受理费25元。”\n"
        "------\n"
        "这个被告的诉讼费已代缴",
        sender="ShanShan",
        minutes=100,
    )

    event = db_session.get(LegalEvent, notice["event_ids"][0])
    metadata = json.loads(event.metadata_json)
    assert metadata["standalone_payment_confirmation"]["message_id"] > 0
    assert result["reminder_ids"] == []
    assert {item.status for item in reminders} == {"sent"}


def test_rejected_duplicate_notice_does_not_make_confirmation_ambiguous(db_session):
    notice = _send(db_session, "李立迁，案号：（2026）冀0109民初7702号，案件受理费25元，请缴费")
    notice_event = db_session.get(LegalEvent, notice["event_ids"][0])
    rejected_event = LegalEvent(
        group_message_id=notice_event.group_message_id,
        event_type="payment_notice",
        amount=notice_event.amount,
        extracted_text=notice_event.extracted_text,
        metadata_json=notice_event.metadata_json,
        attribution_status="not_required",
        business_status="rejected",
    )
    db_session.add(rejected_event)
    db_session.flush()

    _send(
        db_session,
        "李立迁，案号：（2026）冀0109民初7702号，诉讼费已代缴",
        sender="ShanShan",
        minutes=10,
    )

    event = db_session.get(LegalEvent, notice["event_ids"][0])
    assert json.loads(event.metadata_json)["standalone_payment_confirmation"]["message_id"] > 0


def test_multiple_open_notices_are_matched_by_party_and_case_number(db_session):
    first = _send(db_session, "李江胜，案号：（2026）桂0702民初5834号，案件受理费25元，请缴费")
    second = _send(db_session, "王成，案号：（2026）浙0102民初1234号，公告费400元，请缴费", minutes=1)

    _send(db_session, "王成，案号：（2026）浙0102民初1234号，公告费已交", sender="payer", minutes=5)

    first_reminders = list(db_session.scalars(select(Reminder).where(Reminder.source_event_id == first["event_ids"][0])).all())
    second_reminders = list(db_session.scalars(select(Reminder).where(Reminder.source_event_id == second["event_ids"][0])).all())
    assert {item.status for item in first_reminders} == {"pending"}
    assert {item.status for item in second_reminders} == {"cancelled"}


def test_ambiguous_confirmation_does_not_close_multiple_notices(db_session):
    _send(db_session, "李江胜，案件受理费25元，请缴费")
    _send(db_session, "王成，公告费400元，请缴费", minutes=1)

    _send(db_session, "已经交了", sender="payer", minutes=5)

    assert {item.status for item in _reminders(db_session)} == {"pending"}


def test_questions_and_unpaid_statements_do_not_close_notice(db_session):
    _send(db_session, "李江胜，案件受理费25元，请缴费")

    for offset, content in enumerate(("李江胜还没交", "李江胜交了吗", "李江胜是否已交"), start=1):
        _send(db_session, content, sender="checker", minutes=offset)

    assert {item.status for item in _reminders(db_session)} == {"pending"}


def test_repayment_annotation_does_not_close_fee_notice(db_session):
    _send(db_session, "李江胜，案件受理费25元，请缴费")

    _send(db_session, "甲公司+张三+第1期还款+25元", sender="repayment-sender", minutes=5)

    assert {item.status for item in _reminders(db_session)} == {"pending"}


def test_repeated_identical_notice_restarts_followups_from_latest_message(db_session):
    first = _send(db_session, "李江胜，案件受理费25元，请缴费")
    second = _send(db_session, "李江胜，案件受理费25元，请缴费", minutes=2)

    reminders = _reminders(db_session)
    first_reminders = [item for item in reminders if item.source_event_id == first["event_ids"][0]]
    second_reminders = [item for item in reminders if item.source_event_id == second["event_ids"][0]]
    assert {item.status for item in first_reminders} == {"cancelled"}
    assert len(second_reminders) == 2
    assert {item.status for item in second_reminders} == {"pending"}
    second_message = db_session.get(LegalEvent, second["event_ids"][0]).group_message
    assert {round((item.remind_at - second_message.received_at).total_seconds() / 60) for item in second_reminders} == {30, 90}


def test_platform_payment_reminder_callback_is_archived_without_new_event(db_session):
    result = _send(
        db_session,
        '@所有人 【缴费待确认】李江胜，案号：（2026）桂0702民初5834号，案件受理费25.00元，请付款后回复“已缴费”。',
        sender="bot-account",
    )

    assert result["event_ids"] == []
    assert result["reminder_ids"] == []
    assert db_session.scalar(select(LegalEvent.id)) is None
