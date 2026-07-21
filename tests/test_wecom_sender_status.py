import httpx

from app.adapters.wecom_sender_status import WeComSenderStatusClient


def _response(payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "http://sender.test/wecom/finder/health"),
    )


def test_android_sender_health_reports_online_device(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.wecom_sender_status.httpx.get",
        lambda *args, **kwargs: _response(
            {
                "status": "ok",
                "backend": "android",
                "configured": True,
                "target_count": 2,
                "device": {
                    "online": True,
                    "connected_at": "2026-07-21T09:00:00+00:00",
                    "pending_commands": 1,
                },
            }
        ),
    )

    result = WeComSenderStatusClient(
        base_url="http://sender.test",
        timeout_seconds=8,
    ).check()

    assert result == {
        "status": "ok",
        "message": "Android 发送设备在线",
        "backend": "android",
        "configured": True,
        "online": True,
        "connected_at": "2026-07-21T09:00:00+00:00",
        "pending_commands": 1,
        "target_count": 2,
        "status_code": 200,
    }


def test_android_sender_health_distinguishes_mock_and_offline(monkeypatch):
    responses = iter(
        [
            _response(
                {
                    "status": "ok",
                    "backend": "mock",
                    "configured": True,
                    "target_count": 1,
                    "device": {"online": False},
                }
            ),
            _response(
                {
                    "status": "ok",
                    "backend": "android",
                    "configured": True,
                    "target_count": 1,
                    "device": {"online": False},
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "app.adapters.wecom_sender_status.httpx.get",
        lambda *args, **kwargs: next(responses),
    )
    client = WeComSenderStatusClient(base_url="http://sender.test", timeout_seconds=8)

    mock_result = client.check()
    offline_result = client.check()

    assert mock_result["status"] == "degraded"
    assert "Mock" in mock_result["message"]
    assert offline_result["status"] == "error"
    assert offline_result["online"] is False


def test_android_sender_health_sanitizes_connection_failures(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("failed to connect to http://secret-host:8092")

    monkeypatch.setattr("app.adapters.wecom_sender_status.httpx.get", fail)

    result = WeComSenderStatusClient(
        base_url="http://secret-host:8092",
        timeout_seconds=20,
    ).check()

    assert result["status"] == "error"
    assert result["message"] == "发送端 sidecar 无法访问"
    assert result["error_type"] == "ConnectError"
    assert "secret-host" not in str(result)
