from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.merchant_question import MerchantQuestion
from app.models.reminder import Reminder
from app.core.config import get_settings
from app.services.merchant_question_service import MerchantQuestionService
from app.utils.datetime_utils import app_timezone


def _create_group(client, room_id="merchant_group", internal=None, alerts=None, enabled=True):
    response = client.post(
        "/api/v1/legal/wecom-archive/groups",
        json={
            "room_id": room_id,
            "display_name": "商家服务群",
            "status": "enabled",
            "group_type": "merchant",
            "internal_userids": ["staff_001"] if internal is None else internal,
            "alert_userids": ["manager_001"] if alerts is None else alerts,
            "question_timeout_minutes": 5,
            "features": {"question_timeout": enabled},
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def _text(client, group_id, sender_id, content, received_at):
    response = client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": group_id,
            "sender_id": sender_id,
            "msg_type": "text",
            "content": content,
            "received_at": received_at.isoformat(),
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_external_question_times_out_once_and_internal_reply_closes_it(client, db_session):
    group = _create_group(client)
    assert group["group_type"] == "merchant"
    assert group["internal_userids"] == ["staff_001"]
    asked_at = datetime(2026, 7, 20, 9, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "诉讼费今天需要交吗？", asked_at)

    question = db_session.scalar(select(MerchantQuestion))
    assert question.status == "open"
    assert question.deadline_at == asked_at + timedelta(minutes=5)

    service = MerchantQuestionService(db_session)
    first = service.scan_timeouts(asked_at + timedelta(minutes=6))
    second = service.scan_timeouts(asked_at + timedelta(minutes=7))
    db_session.commit()
    assert first == {"checked": 1, "created_reminders": 1, "created_escalations": 0}
    assert second == {"checked": 0, "created_reminders": 0, "created_escalations": 0}
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "merchant_question_timeout")).all())
    assert len(reminders) == 1
    assert reminders[0].target_userid == "manager_001"

    _text(client, "merchant_group", "staff_001", "需要，今天下班前完成。", asked_at + timedelta(minutes=8))
    db_session.expire_all()
    question = db_session.get(MerchantQuestion, question.id)
    reminder = db_session.get(Reminder, reminders[0].id)
    assert question.status == "replied"
    assert question.reply_message_id is not None
    assert reminder.status == "cancelled"


def test_one_internal_reply_closes_only_latest_question_in_same_group(client, db_session):
    _create_group(client, "merchant_a")
    _create_group(client, "merchant_b")
    now = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())
    _text(client, "merchant_a", "merchant_1", "问题一", now)
    _text(client, "merchant_a", "merchant_2", "问题二", now + timedelta(minutes=1))
    _text(client, "merchant_b", "merchant_3", "另一个群的问题", now + timedelta(minutes=1))

    _text(client, "merchant_a", "staff_001", "统一回复", now + timedelta(minutes=2))
    db_session.expire_all()
    group_a = list(db_session.scalars(select(MerchantQuestion).where(MerchantQuestion.group_id == "merchant_a")).all())
    group_b = list(db_session.scalars(select(MerchantQuestion).where(MerchantQuestion.group_id == "merchant_b")).all())
    assert [question.status for question in group_a] == ["open", "replied"]
    assert group_b[0].status == "open"


def test_question_timeout_feature_can_be_disabled(client, db_session):
    _create_group(client, "merchant_disabled", enabled=False)
    _text(
        client,
        "merchant_disabled",
        "merchant_001",
        "不会创建问题",
        datetime(2026, 7, 20, 11, 0, tzinfo=app_timezone()),
    )

    assert db_session.scalar(select(MerchantQuestion)) is None


def test_question_deadline_uses_business_hours_and_escalates(client, db_session, monkeypatch):
    monkeypatch.setenv("MERCHANT_WORKDAY_START", "09:00")
    monkeypatch.setenv("MERCHANT_WORKDAY_END", "18:00")
    monkeypatch.setenv("MERCHANT_WORKDAYS", "0,1,2,3,4")
    monkeypatch.setenv("MERCHANT_QUESTION_ESCALATION_MINUTES", "30")
    get_settings.cache_clear()
    _create_group(client, alerts=["owner_001", "supervisor_001"])
    friday_evening = datetime(2026, 7, 24, 19, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "周末前的问题", friday_evening)
    question = db_session.scalar(select(MerchantQuestion))

    assert question.deadline_at == datetime(2026, 7, 27, 9, 5, tzinfo=app_timezone())
    service = MerchantQuestionService(db_session)
    timeout = service.scan_timeouts(datetime(2026, 7, 27, 9, 6, tzinfo=app_timezone()))
    followup = service.scan_timeouts(datetime(2026, 7, 27, 9, 31, tzinfo=app_timezone()))
    escalation = service.scan_timeouts(datetime(2026, 7, 27, 10, 1, tzinfo=app_timezone()))
    final_scan = service.scan_timeouts(datetime(2026, 7, 27, 11, 1, tzinfo=app_timezone()))
    reminders = list(db_session.scalars(select(Reminder).order_by(Reminder.id)).all())

    assert timeout["created_reminders"] == 1
    assert followup["created_escalations"] == 1
    assert escalation["created_escalations"] == 1
    assert final_scan["created_escalations"] == 0
    assert [item.reminder_type for item in reminders] == [
        "merchant_question_timeout",
        "merchant_question_followup",
        "merchant_question_escalation",
    ]
    assert [item.target_userid for item in reminders] == ["owner_001", "owner_001", "supervisor_001"]
    assert "等待 5 分钟" in reminders[0].content
    assert "等待 30 分钟" in reminders[1].content
    assert "等待 60 分钟" in reminders[2].content
    assert question.status == "escalated"
    assert reminders[-1].reminder_type == "merchant_question_escalation"
    assert reminders[-1].target_userid == "supervisor_001"
    get_settings.cache_clear()


def test_system_generated_messages_do_not_create_questions(client, db_session):
    _create_group(client)
    now = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())

    for index, content in enumerate(
        (
            "【致和法务】企业微信发送通道测试成功。",
            "【商家待回复】消息已等待 5 分钟，请尽快回复。",
            "商家消息超过 5 分钟未回复：旧提醒",
            "商家消息超时后仍未回复，已升级：旧提醒",
        )
    ):
        _text(client, "merchant_group", "system_sender", content, now + timedelta(seconds=index))

    assert db_session.scalar(select(MerchantQuestion)) is None


def test_system_generated_internal_message_does_not_close_real_question(client, db_session):
    _create_group(client, internal=["system_sender"])
    asked_at = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "真实商家问题", asked_at)

    _text(
        client,
        "merchant_group",
        "system_sender",
        "【商家待回复】消息已等待 5 分钟，请尽快回复：真实商家问题",
        asked_at + timedelta(minutes=5),
    )

    question = db_session.scalar(select(MerchantQuestion))
    assert question.status == "open"


def test_conversation_closing_messages_do_not_create_questions(client, db_session):
    _create_group(client)
    now = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())

    for index, content in enumerate(("好的，谢谢", "收到，辛苦了", "已经解决了", "暂时不用了")):
        _text(client, "merchant_group", f"merchant_{index}", content, now + timedelta(seconds=index))

    assert db_session.scalar(select(MerchantQuestion)) is None


def test_closing_message_closes_same_senders_pending_question_and_reminders(client, db_session):
    _create_group(client)
    asked_at = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "诉讼费今天需要交吗？", asked_at)
    service = MerchantQuestionService(db_session)
    service.scan_timeouts(asked_at + timedelta(minutes=6))
    question = db_session.scalar(select(MerchantQuestion))
    reminder = db_session.scalar(select(Reminder))
    assert question.status == "timed_out"
    assert reminder.status == "pending"
    db_session.commit()

    _text(client, "merchant_group", "merchant_001", "不用了，已经解决，谢谢", asked_at + timedelta(minutes=7))
    db_session.expire_all()

    assert db_session.get(MerchantQuestion, question.id).status == "closed"
    assert db_session.get(MerchantQuestion, question.id).close_reason == "商家确认对话结束，无需回复"
    assert db_session.get(Reminder, reminder.id).status == "cancelled"
    assert len(list(db_session.scalars(select(MerchantQuestion)).all())) == 1


def test_action_request_is_not_misclassified_as_conversation_closing(client, db_session):
    _create_group(client)
    now = datetime(2026, 7, 20, 10, 0, tzinfo=app_timezone())

    _text(client, "merchant_group", "merchant_001", "好的，麻烦再核实一下，谢谢", now)

    question = db_session.scalar(select(MerchantQuestion))
    assert question is not None
    assert question.status == "open"


def test_internal_reply_cancels_all_pending_timeout_stages(client, db_session, monkeypatch):
    monkeypatch.setenv("MERCHANT_QUESTION_ESCALATION_MINUTES", "30")
    get_settings.cache_clear()
    _create_group(client)
    asked_at = datetime(2026, 7, 20, 9, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "需要回复的问题", asked_at)
    service = MerchantQuestionService(db_session)
    service.scan_timeouts(asked_at + timedelta(minutes=61))
    db_session.commit()
    reminders = list(db_session.scalars(select(Reminder).order_by(Reminder.id)).all())
    assert len(reminders) == 3
    assert {item.status for item in reminders} == {"pending"}

    _text(client, "merchant_group", "staff_001", "已经处理", asked_at + timedelta(minutes=62))
    db_session.expire_all()

    assert {db_session.get(Reminder, item.id).status for item in reminders} == {"cancelled"}
    get_settings.cache_clear()


def test_timeout_without_alert_target_does_not_send_unmentioned_message(client, db_session):
    _create_group(client, alerts=[])
    asked_at = datetime(2026, 7, 20, 9, 0, tzinfo=app_timezone())
    _text(client, "merchant_group", "merchant_001", "请尽快回复", asked_at)

    result = MerchantQuestionService(db_session).scan_timeouts(asked_at + timedelta(minutes=6))

    assert result["created_reminders"] == 0
    assert db_session.scalar(select(Reminder)) is None


def test_question_can_be_manually_closed(client, db_session):
    _create_group(client)
    _text(
        client,
        "merchant_group",
        "merchant_001",
        "请人工关闭",
        datetime(2026, 7, 20, 12, 0, tzinfo=app_timezone()),
    )
    question = db_session.scalar(select(MerchantQuestion))

    response = client.post(
        f"/api/v1/legal/merchant-questions/{question.id}/close",
        json={"reason": "电话已回复"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "closed"
    assert response.json()["data"]["close_reason"] == "电话已回复"
