import os
from datetime import datetime

import httpx

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


def test_wecom_webhook_without_url_fails_without_crash():
    reset_settings(WECOM_SEND_MODE="webhook", WECOM_WEBHOOK_URL="")
    result = WeComMessageAdapter().send_text("group_001", "测试消息")
    assert result["success"] is False
    assert result["mode"] == "webhook"
    assert result["status_code"] is None
    assert "WECOM_WEBHOOK_URL" in result["error"]


def test_run_due_mock_marks_simulated_and_returns_stats(client, db_session):
    reset_settings(WECOM_SEND_MODE="mock", WECOM_WEBHOOK_URL="")
    reminder_id = create_due_reminder(client)
    response = client.post("/api/v1/legal/reminders/run-due")
    assert response.status_code == 200
    assert response.json()["data"] == {"sent": 0, "simulated": 1, "failed": 0, "retrying": 0, "total": 1}

    reminder = db_session.get(Reminder, reminder_id)
    assert reminder.status == "simulated"
    assert reminder.sent_at is None


def test_webhook_errcode_failure_increments_retry_count(client, db_session, monkeypatch):
    reset_settings(WECOM_SEND_MODE="webhook", WECOM_WEBHOOK_URL="https://example.test/webhook", WECOM_MAX_RETRY=3)
    reminder_id = create_due_reminder(client)

    def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    monkeypatch.setattr("app.adapters.wecom_message.httpx.post", fake_post)
    response = client.post("/api/v1/legal/reminders/run-due")

    assert response.json()["data"] == {"sent": 0, "simulated": 0, "failed": 0, "retrying": 1, "total": 1}
    reminder = db_session.get(Reminder, reminder_id)
    assert reminder.status == "pending"
    assert reminder.retry_count == 1
    assert "errcode=93000" in reminder.last_error


def test_retry_count_reaches_max_retry_marks_failed(client, db_session, monkeypatch):
    reset_settings(WECOM_SEND_MODE="webhook", WECOM_WEBHOOK_URL="https://example.test/webhook", WECOM_MAX_RETRY=1)
    reminder_id = create_due_reminder(client)

    def fake_post(*args, **kwargs):
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    monkeypatch.setattr("app.adapters.wecom_message.httpx.post", fake_post)
    response = client.post("/api/v1/legal/reminders/run-due")

    assert response.json()["data"] == {"sent": 0, "simulated": 0, "failed": 1, "retrying": 0, "total": 1}
    reminder = db_session.get(Reminder, reminder_id)
    assert reminder.status == "failed"
    assert reminder.retry_count == 1


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


def test_run_due_stats_include_sent_failed_retrying_total(client, monkeypatch):
    reset_settings(WECOM_SEND_MODE="webhook", WECOM_WEBHOOK_URL="https://example.test/webhook", WECOM_MAX_RETRY=2)
    create_due_reminder(client, content="成功提醒")
    create_due_reminder(client, content="重试提醒")

    def fake_post(url, json, timeout):
        if json["text"]["content"] == "成功提醒":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
        return httpx.Response(200, json={"errcode": 93000, "errmsg": "invalid webhook"})

    monkeypatch.setattr("app.adapters.wecom_message.httpx.post", fake_post)
    response = client.post("/api/v1/legal/reminders/run-due")

    assert response.status_code == 200
    assert response.json()["data"] == {"sent": 1, "simulated": 0, "failed": 0, "retrying": 1, "total": 2}
