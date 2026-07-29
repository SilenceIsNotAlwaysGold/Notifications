from sqlalchemy import select

from app.models.group_message import GroupMessage
from app.models.legal_event import LegalEvent
from app.models.merchant_question import MerchantQuestion
from app.models.reminder import Reminder
from app.schemas.legal import MockMessageCreate, WeComArchiveGroupCreate
from app.services.message_service import MessageService
from app.services.wecom_archive_group_service import WeComArchiveGroupService


def test_non_business_chat_is_context_only(db_session):
    result = MessageService(db_session).handle_incoming_message(
        MockMessageCreate(
            group_id="context_group",
            sender_id="u1",
            msg_type="text",
            content="嗯 问下客服",
        )
    )

    assert result["event_ids"] == []
    assert db_session.scalar(select(LegalEvent)) is None
    assert db_session.scalar(select(GroupMessage)).content == "嗯 问下客服"


def test_backfill_payment_notice_never_creates_realtime_reminders(db_session):
    result = MessageService(db_session).handle_incoming_message(
        MockMessageCreate(
            group_id="payment_group",
            sender_id="notice_sender",
            msg_type="text",
            content="李江胜，案件受理费25元，请在8月2日前缴费",
            processing_mode="backfill",
        )
    )

    event = db_session.get(LegalEvent, result["event_ids"][0])
    message = db_session.get(GroupMessage, result["group_message_id"])
    assert event.event_type == "payment_notice"
    assert event.attribution_status == "not_required"
    assert message.processing_mode == "backfill"
    assert result["reminder_ids"] == []
    assert db_session.scalar(select(Reminder)) is None


def test_backfill_merchant_question_is_not_opened(db_session):
    WeComArchiveGroupService(db_session).create_group(
        WeComArchiveGroupCreate(
            room_id="merchant_group",
            status="enabled",
            group_type="merchant",
            features={"question_timeout": True},
        )
    )

    MessageService(db_session).handle_incoming_message(
        MockMessageCreate(
            group_id="merchant_group",
            sender_id="merchant_user",
            msg_type="text",
            content="麻烦核实一下是否已结清",
            processing_mode="backfill",
        )
    )

    assert db_session.scalar(select(MerchantQuestion)) is None
    assert db_session.scalar(select(Reminder)) is None
