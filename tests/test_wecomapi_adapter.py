import httpx

from app.adapters.wecom_message import WeComMessageAdapter
from app.adapters.wecomapi import WeComApiAdapter
from app.core.config import get_settings
from app.models.wecom_archive_group import WeComArchiveGroup


def _configure_wecomapi(monkeypatch, *, threshold: int = 3) -> None:
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("WECOMAPI_API_PATH", "/wecom/finder/api")
    monkeypatch.setenv("WECOMAPI_TOKEN", "dedicated-account-token")
    monkeypatch.setenv("WECOMAPI_GUID", "dedicated-account-guid")
    monkeypatch.setenv("WECOMAPI_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("WECOMAPI_DAILY_LIMIT", "200")
    monkeypatch.setenv("WECOMAPI_FAILURE_THRESHOLD", str(threshold))
    monkeypatch.setenv("WECOMAPI_COOLDOWN_SECONDS", "300")
    get_settings.cache_clear()
    WeComApiAdapter.reset_safety_state()


def test_wecomapi_send_uses_explicit_room_mapping(db_session, monkeypatch):
    _configure_wecomapi(monkeypatch)
    db_session.add(
        WeComArchiveGroup(
            room_id="wr_official_001",
            wecomapi_room_id="1081379876227242",
            display_name="致和法务执行群",
            status="enabled",
        )
    )
    db_session.commit()
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return httpx.Response(200, json={"code": 0, "msg": "成功", "data": {"msgId": "msg-001"}})

    monkeypatch.setattr("app.adapters.wecomapi.httpx.post", fake_post)

    result = WeComMessageAdapter().send_text("wr_official_001", "开庭提醒")

    assert result["success"] is True
    assert result["mode"] == "wecomapi"
    assert captured["url"] == "https://gateway.example.test/wecom/finder/api"
    assert captured["headers"]["WECOM-TOKEN"] == "dedicated-account-token"
    assert captured["json"] == {
        "method": "/msg/sendText",
        "params": {
            "guid": "dedicated-account-guid",
            "toId": "1081379876227242",
            "content": "开庭提醒",
        },
    }


def test_wecomapi_send_without_room_mapping_is_blocked(db_session, monkeypatch):
    _configure_wecomapi(monkeypatch)
    db_session.add(
        WeComArchiveGroup(
            room_id="wr_official_002",
            display_name="未完成映射的群",
            status="enabled",
        )
    )
    db_session.commit()
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return httpx.Response(200, json={"code": 0})

    monkeypatch.setattr("app.adapters.wecomapi.httpx.post", fake_post)

    result = WeComMessageAdapter().send_text("wr_official_002", "缴费提醒")

    assert result["success"] is False
    assert "未配置 wecomapi 协议群 ID" in result["error"]
    assert called is False


def test_wecomapi_circuit_breaker_stops_requests_after_consecutive_failures(monkeypatch):
    _configure_wecomapi(monkeypatch, threshold=2)
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"code": 500, "msg": "账号离线"})

    monkeypatch.setattr("app.adapters.wecomapi.httpx.post", fake_post)
    adapter = WeComApiAdapter(
        base_url="https://gateway.example.test",
        api_path="/wecom/finder/api",
        token="dedicated-account-token",
        guid="dedicated-account-guid",
        timeout_seconds=8,
        min_interval_seconds=0,
        daily_limit=200,
        failure_threshold=2,
        cooldown_seconds=300,
    )

    assert adapter.send_text("room-1", "提醒一")["success"] is False
    assert adapter.send_text("room-1", "提醒二")["success"] is False
    blocked = adapter.send_text("room-1", "提醒三")

    assert blocked["success"] is False
    assert "熔断中" in blocked["error"]
    assert calls == 2
