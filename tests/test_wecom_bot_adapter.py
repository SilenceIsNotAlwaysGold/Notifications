import httpx

from app.adapters.wecom_bot import WeComBotAdapter
from app.adapters.wecom_message import WeComMessageAdapter
from app.core.config import get_settings
from app.models.wecom_archive_group import WeComArchiveGroup


def _configure_bot(monkeypatch, *, group_daily_limit: int = 10) -> None:
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_bot")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_URL", "http://127.0.0.1:8788")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_TOKEN", "test-sidecar-token-123456")
    monkeypatch.setenv("WECOM_BOT_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("WECOM_BOT_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("WECOM_BOT_DAILY_LIMIT", "200")
    monkeypatch.setenv("WECOM_BOT_GROUP_DAILY_LIMIT", str(group_daily_limit))
    monkeypatch.setenv("WECOM_BOT_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("WECOM_BOT_COOLDOWN_SECONDS", "300")
    get_settings.cache_clear()
    WeComBotAdapter.reset_safety_state()


def test_official_bot_sends_to_enabled_archive_room(db_session, monkeypatch):
    _configure_bot(monkeypatch)
    db_session.add(
        WeComArchiveGroup(
            room_id="wrOfficialBot001",
            display_name="致和法务执行群",
            status="enabled",
        )
    )
    db_session.commit()
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={
                "success": True,
                "room_id": "wrOfficialBot001",
                "message_id": "request-001",
            },
        )

    monkeypatch.setattr("app.adapters.wecom_bot.httpx.post", fake_post)

    result = WeComMessageAdapter().send_text("wrOfficialBot001", "开庭提醒")

    assert result["success"] is True
    assert result["mode"] == "wecom_bot"
    assert captured["url"] == "http://127.0.0.1:8788/send-text"
    assert captured["headers"]["Authorization"] == "Bearer test-sidecar-token-123456"
    assert captured["json"] == {
        "room_id": "wrOfficialBot001",
        "content": "开庭提醒",
    }


def test_official_bot_blocks_disabled_archive_room(db_session, monkeypatch):
    _configure_bot(monkeypatch)
    db_session.add(
        WeComArchiveGroup(
            room_id="wrOfficialBot002",
            display_name="未启用群",
            status="disabled",
        )
    )
    db_session.commit()
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("disabled group must not invoke the bot sidecar")

    monkeypatch.setattr("app.adapters.wecom_bot.httpx.post", fake_post)

    result = WeComMessageAdapter().send_text("wrOfficialBot002", "缴费提醒")

    assert result["success"] is False
    assert "未在归档群管理中启用" in result["error"]
    assert called is False


def test_official_bot_reports_sidecar_error(monkeypatch):
    _configure_bot(monkeypatch)

    def fake_post(*args, **kwargs):
        return httpx.Response(503, json={"success": False, "error": "企业微信机器人尚未连接"})

    monkeypatch.setattr("app.adapters.wecom_bot.httpx.post", fake_post)
    adapter = WeComBotAdapter(
        base_url="http://127.0.0.1:8788",
        token="test-sidecar-token-123456",
        timeout_seconds=10,
        min_interval_seconds=0,
        daily_limit=200,
        group_daily_limit=10,
        failure_threshold=3,
        cooldown_seconds=300,
    )

    result = adapter.send_text("wrOfficialBot003", "提醒")

    assert result["success"] is False
    assert "HTTP 503" in result["error"]
    assert "尚未连接" in result["error"]


def test_official_bot_enforces_utf8_and_group_daily_limits(monkeypatch):
    _configure_bot(monkeypatch, group_daily_limit=1)
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"success": True, "message_id": "request-001"})

    monkeypatch.setattr("app.adapters.wecom_bot.httpx.post", fake_post)
    adapter = WeComBotAdapter(
        base_url="http://127.0.0.1:8788",
        token="test-sidecar-token-123456",
        timeout_seconds=10,
        min_interval_seconds=0,
        daily_limit=200,
        group_daily_limit=1,
        failure_threshold=3,
        cooldown_seconds=300,
    )

    assert adapter.send_text("wrOfficialBot004", "第一次提醒")["success"] is True
    blocked = adapter.send_text("wrOfficialBot004", "第二次提醒")
    oversized = adapter.send_text("wrOfficialBot005", "法" * 683)

    assert "每日发送上限 1" in blocked["error"]
    assert "2048 个 UTF-8 字节" in oversized["error"]
    assert calls == 1
