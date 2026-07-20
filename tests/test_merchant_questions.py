from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.merchant_question import MerchantQuestion
from app.models.reminder import Reminder
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
            "internal_userids": internal or ["staff_001"],
            "alert_userids": alerts or ["manager_001"],
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
    assert first == {"checked": 1, "created_reminders": 1}
    assert second == {"checked": 0, "created_reminders": 0}
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


def test_one_internal_reply_closes_all_previous_questions_in_same_group_only(client, db_session):
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
    assert all(question.status == "replied" for question in group_a)
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
