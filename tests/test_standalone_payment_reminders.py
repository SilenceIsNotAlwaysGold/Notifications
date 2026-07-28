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
    assert event.attribution_status == "pending"
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


def test_repeated_identical_notice_does_not_duplicate_followups(db_session):
    first = _send(db_session, "李江胜，案件受理费25元，请缴费")
    second = _send(db_session, "李江胜，案件受理费25元，请缴费", minutes=2)

    reminders = _reminders(db_session)
    assert len(reminders) == 2
    assert {item.source_event_id for item in reminders} == {first["event_ids"][0]}
    assert second["reminder_ids"] == []
