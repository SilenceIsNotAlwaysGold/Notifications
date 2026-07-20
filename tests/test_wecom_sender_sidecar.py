from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from wecom_sender_sidecar.main import app, sender_manager


def _configure_sender(monkeypatch, *, backend: str = "mock") -> None:
    monkeypatch.setenv("WECOM_SENDER_BACKEND", backend)
    monkeypatch.setenv("WECOM_SENDER_API_TOKEN", "sidecar-api-token")
    monkeypatch.setenv("WECOM_SENDER_ROBOT_ID", "robot-zhihe-001")
    monkeypatch.setenv(
        "WECOM_SENDER_TARGETS_JSON",
        '{"zhihe-legal":"致和法务执行群"}',
    )
    monkeypatch.setenv("WECOM_SENDER_COMMAND_TIMEOUT_SECONDS", "2")


def _request_payload() -> dict:
    return {
        "method": "/msg/sendText",
        "params": {
            "guid": "robot-zhihe-001",
            "toId": "zhihe-legal",
            "content": "开庭提醒：明日上午九点开庭。",
        },
    }


def test_mock_gateway_uses_target_whitelist(monkeypatch):
    _configure_sender(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/wecom/finder/api",
            headers={"WECOM-TOKEN": "sidecar-api-token"},
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
            headers={"WECOM-TOKEN": "sidecar-api-token"},
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
        with client.websocket_connect("/webserver/wework/robot-zhihe-001") as device:
            with ThreadPoolExecutor(max_workers=1) as executor:
                request_future = executor.submit(
                    client.post,
                    "/wecom/finder/api",
                    headers={"WECOM-TOKEN": "sidecar-api-token"},
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
            headers={"WECOM-TOKEN": "sidecar-api-token"},
            json=_request_payload(),
        )

    assert response.status_code == 200
    assert response.json()["code"] == 5001
    assert "不在线" in response.json()["msg"]

    # Keep the process-global manager clean for the rest of the test suite.
    import asyncio

    asyncio.run(sender_manager.reset())
