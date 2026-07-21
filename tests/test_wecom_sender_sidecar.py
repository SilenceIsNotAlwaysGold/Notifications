from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from wecom_sender_sidecar.main import app, sender_manager


API_TOKEN = "sidecar-api-token-32-characters-long"
ROBOT_ID = "robot-zhihe-001-32-characters-long"


def _configure_sender(monkeypatch, *, backend: str = "mock") -> None:
    monkeypatch.setenv("WECOM_SENDER_BACKEND", backend)
    monkeypatch.setenv("WECOM_SENDER_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("WECOM_SENDER_ROBOT_ID", ROBOT_ID)
    monkeypatch.setenv(
        "WECOM_SENDER_TARGETS_JSON",
        '{"zhihe-legal":"致和法务执行群"}',
    )
    monkeypatch.setenv("WECOM_SENDER_COMMAND_TIMEOUT_SECONDS", "2")


def _request_payload() -> dict:
    return {
        "method": "/msg/sendText",
        "params": {
            "guid": ROBOT_ID,
            "toId": "zhihe-legal",
            "content": "开庭提醒：明日上午九点开庭。",
        },
    }


def test_mock_gateway_uses_target_whitelist(monkeypatch):
    _configure_sender(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/wecom/finder/api",
            headers={"WECOM-TOKEN": API_TOKEN},
            json=_request_payload(),
        )

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"]["groupName"] == "致和法务执行群"
    assert response.json()["data"]["mock"] is True


def test_gateway_rejects_unknown_target(monkeypatch):
    _configure_sender(monkeypatch)
    payload = _request_payload()
    payload["params"]["toId"] = "unknown-room"

    with TestClient(app) as client:
        response = client.post(
            "/wecom/finder/api",
            headers={"WECOM-TOKEN": API_TOKEN},
            json=payload,
        )

    assert response.status_code == 200
    assert response.json()["code"] == 4004
    assert "白名单" in response.json()["msg"]


def test_gateway_rejects_invalid_token(monkeypatch):
    _configure_sender(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/wecom/finder/api",
            headers={"WECOM-TOKEN": "wrong-token"},
            json=_request_payload(),
        )

    assert response.status_code == 401


def test_worktool_websocket_receives_command_and_returns_receipt(monkeypatch):
    _configure_sender(monkeypatch, backend="worktool")

    with TestClient(app) as client:
        with client.websocket_connect(f"/webserver/wework/{ROBOT_ID}") as device:
            with ThreadPoolExecutor(max_workers=1) as executor:
                request_future = executor.submit(
                    client.post,
                    "/wecom/finder/api",
                    headers={"WECOM-TOKEN": API_TOKEN},
                    json=_request_payload(),
                )
                command = device.receive_json()
                assert command["socketType"] == 2
                assert command["list"][0]["type"] == 203
                assert command["list"][0]["titleList"] == ["致和法务执行群"]
                device.send_json(
                    {
                        "socketType": 3,
                        "messageId": command["messageId"],
                        "list": [
                            {
                                "errorCode": 0,
                                "errorReason": "",
                                "successList": ["致和法务执行群"],
                            }
                        ],
                    }
                )
                response = request_future.result(timeout=5)

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"]["callback"]["errorCode"] == 0


def test_worktool_backend_reports_offline_device(monkeypatch):
    _configure_sender(monkeypatch, backend="worktool")

    with TestClient(app) as client:
        response = client.post(
            "/wecom/finder/api",
            headers={"WECOM-TOKEN": API_TOKEN},
            json=_request_payload(),
        )

    assert response.status_code == 200
    assert response.json()["code"] == 5001
    assert "不在线" in response.json()["msg"]

    # Keep the process-global manager clean for the rest of the test suite.
    import asyncio

    asyncio.run(sender_manager.reset())


def test_worktool_backend_rejects_weak_device_credentials(monkeypatch):
    _configure_sender(monkeypatch, backend="worktool")
    monkeypatch.setenv("WECOM_SENDER_API_TOKEN", "short")

    with pytest.raises(RuntimeError, match="API_TOKEN 至少 24 位"):
        from wecom_sender_sidecar.main import load_config

        load_config()
