import os
from datetime import datetime

from app.adapters.wecom_message import WeComMessageAdapter
from app.core.config import get_settings
from app.models.reminder import Reminder
from app.services.reminder_service import ReminderService
from app.utils.datetime_utils import ensure_aware


def reset_settings(**env_values):
    for key, value in env_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    get_settings.cache_clear()


def create_due_reminder(client, content="到期提醒", target_userid="lawyer_001"):
    response = client.post(
        "/api/v1/legal/reminders/custom",
        json={
            "group_id": "group_001",
            "remind_at": "2026-06-02T09:00:00+08:00",
            "content": content,
            "target_userid": target_userid,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def test_wecom_mock_mode_send_success():
    reset_settings(WECOM_SEND_MODE="mock", WECOM_WEBHOOK_URL="")
    result = WeComMessageAdapter().send_text("group_001", "测试消息", mentioned_userids=["lawyer_001"])
    assert result == {
        "success": True,
        "mode": "mock",
        "status_code": None,
        "response": {
            "mock": True,
            "payload": {
                "msgtype": "text",
                "text": {
                    "content": "测试消息",
                    "mentioned_list": ["lawyer_001"],
                    "mentioned_mobile_list": [],
                },
            },
        },
        "error": None,
    }


def test_run_due_mock_marks_simulated_and_returns_stats(client, db_session):
    reset_settings(WECOM_SEND_MODE="mock", WECOM_WEBHOOK_URL="")
    reminder_id = create_due_reminder(client)
    response = client.post("/api/v1/legal/reminders/run-due")
    assert response.status_code == 200
    assert response.json()["data"] == {"sent": 0, "simulated": 1, "failed": 0, "retrying": 0, "total": 1}

    reminder = db_session.get(Reminder, reminder_id)
    assert reminder.status == "simulated"
    assert reminder.sent_at is None


def test_target_userid_is_passed_as_mentioned_userids(db_session):
    captured = {}

    class FakeWeComAdapter:
        settings = type("Settings", (), {"wecom_max_retry": 3})()

        def send_text(self, group_id, content, mentioned_userids=None, mentioned_mobiles=None):
            captured["group_id"] = group_id
            captured["content"] = content
            captured["mentioned_userids"] = mentioned_userids
            captured["mentioned_mobiles"] = mentioned_mobiles
            return {"success": True, "mode": "mock", "status_code": None, "response": {}, "error": None}

    reminder = Reminder(
        group_id="group_001",
        reminder_type="custom",
        remind_at=ensure_aware(datetime.fromisoformat("2026-06-02T09:00:00+08:00")),
        content="需要 @ 法务",
        target_userid="lawyer_001",
        status="pending",
    )
    db_session.add(reminder)
    db_session.commit()

    result = ReminderService(db_session, wecom_adapter=FakeWeComAdapter()).send_due_reminders()
    db_session.commit()

    assert result == {"sent": 0, "simulated": 1, "failed": 0, "retrying": 0, "total": 1}
    assert captured["mentioned_userids"] == ["lawyer_001"]
    assert captured["mentioned_mobiles"] is None
