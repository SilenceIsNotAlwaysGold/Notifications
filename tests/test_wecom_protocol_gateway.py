import json
import sqlite3
import subprocess

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from wecom_protocol_gateway.main import app


def _configure_gateway(monkeypatch, tmp_path, *, backend: str = "mock") -> None:
    monkeypatch.setenv("WECOM_PROTOCOL_BACKEND", backend)
    monkeypatch.setenv("WECOM_PROTOCOL_API_TOKEN", "gateway-api-token")
    monkeypatch.setenv("WECOM_PROTOCOL_GUID", "device-zhihe-001")
    monkeypatch.setenv(
        "WECOM_PROTOCOL_ROOM_IDS_JSON",
        '{"zhihe-legal":"wr-external-room-001"}',
    )
    monkeypatch.setenv("WECOM_PROTOCOL_ALLOW_RAW_ROOM_IDS", "false")
    monkeypatch.setenv(
        "WECOM_PROTOCOL_STATE_DB", str(tmp_path / "protocol-gateway.db")
    )
    monkeypatch.setenv(
        "WECOM_PROTOCOL_STATE_KEY", Fernet.generate_key().decode("ascii")
    )
    monkeypatch.setenv("WECOM_PROTOCOL_CALLBACK_RETRY_SECONDS", "3600")
    if backend == "upstream":
        monkeypatch.setenv(
            "WECOM_PROTOCOL_UPSTREAM_BASE_URL", "https://upstream.example.test"
        )
        monkeypatch.setenv("WECOM_PROTOCOL_UPSTREAM_API_PATH", "/api/qw/doApi")
        monkeypatch.setenv("WECOM_PROTOCOL_UPSTREAM_TOKEN", "upstream-secret")
        monkeypatch.setenv(
            "WECOM_PROTOCOL_UPSTREAM_CALLBACK_TOKEN", "upstream-callback-secret"
        )
    if backend == "official_cli":
        binary = tmp_path / "wecom-cli"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        config_dir = tmp_path / "wecom-cli-config"
        config_dir.mkdir()
        for name in (".encryption_key", "bot.enc", "mcp_config.enc"):
            (config_dir / name).write_bytes(b"encrypted-test-data")
        monkeypatch.setenv("WECOM_PROTOCOL_OFFICIAL_CLI_BINARY", str(binary))
        monkeypatch.setenv(
            "WECOM_PROTOCOL_OFFICIAL_CLI_CONFIG_DIR", str(config_dir)
        )
        monkeypatch.setenv("WECOM_PROTOCOL_OFFICIAL_CLI_TIMEOUT_SECONDS", "10")


def _headers() -> dict[str, str]:
    return {"WECOM-TOKEN": "gateway-api-token"}


def _send_payload() -> dict:
    return {
        "method": "/msg/sendText",
        "params": {
            "guid": "device-zhihe-001",
            "toId": "zhihe-legal",
            "content": "开庭提醒：明日上午九点开庭。",
        },
    }


def _successful_cli_result() -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"errcode": 0, "errmsg": "ok", "msgid": "msg-001"}
                        ),
                    }
                ]
            },
        }
    )


def test_mock_gateway_sends_to_mapped_external_room(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", headers=_headers(), json=_send_payload())
        health = client.get("/health")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"]["toId"] == "wr-external-room-001"
    assert response.json()["data"]["mock"] is True
    assert health.json()["driver"]["backend"] == "mock"
    assert health.json()["configured_guid"] == "dev***001"


def test_gateway_blocks_unknown_room_and_method(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path)
    payload = _send_payload()
    payload["params"]["toId"] = "unapproved-room"

    with TestClient(app) as client:
        room_response = client.post(
            "/wecom/finder/api", headers=_headers(), json=payload
        )
        method_response = client.post(
            "/api/qw/doApi",
            headers=_headers(),
            json={"method": "/room/dismissRoom", "params": {}},
        )

    assert room_response.json()["code"] == 4002
    assert "白名单" in room_response.json()["msg"]
    assert method_response.json()["code"] == 4001


def test_gateway_renames_only_mapped_room(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path)
    payload = {
        "method": "/room/modifyRoomName",
        "params": {
            "guid": "device-zhihe-001",
            "roomId": "zhihe-legal",
            "name": "致和法务执行群",
        },
    }

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", headers=_headers(), json=payload)

    assert response.json() == {
        "code": 0,
        "msg": "成功",
        "data": {
            "roomId": "wr-external-room-001",
            "name": "致和法务执行群",
            "mock": True,
        },
    }


def test_upstream_driver_forwards_normalized_request(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path, backend="upstream")
    captured = {}

    async def fake_post(self, url, *, headers, json):
        captured.update(url=url, headers=headers, json=json)
        from httpx import Response

        return Response(200, json={"code": 0, "msg": "成功", "data": {"ok": True}})

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", headers=_headers(), json=_send_payload())

    assert response.json()["code"] == 0
    assert captured["url"] == "https://upstream.example.test/api/qw/doApi"
    assert captured["headers"]["WECOM-TOKEN"] == "upstream-secret"
    assert captured["json"]["params"]["toId"] == "wr-external-room-001"


def test_upstream_can_create_device_before_guid_is_bound(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path, backend="upstream")
    monkeypatch.setenv("WECOM_PROTOCOL_GUID", "")

    async def fake_post(self, url, *, headers, json):
        from httpx import Response

        assert json == {"method": "/login/createDevice", "params": {}}
        return Response(
            200,
            json={"code": 0, "msg": "成功", "data": {"guid": "created-guid"}},
        )

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)

    with TestClient(app) as client:
        created = client.post(
            "/api/qw/doApi",
            headers=_headers(),
            json={"method": "/login/createDevice", "params": {}},
        )
        blocked = client.post(
            "/api/qw/doApi", headers=_headers(), json=_send_payload()
        )

    assert created.json()["data"]["guid"] == "created-guid"
    assert blocked.json()["code"] == 4002
    assert "尚未绑定 guid" in blocked.json()["msg"]


def test_official_cli_driver_sends_mapped_external_room(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path, backend="official_cli")
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=_successful_cli_result(),
            stderr="",
        )

    monkeypatch.setattr(
        "wecom_protocol_gateway.official_cli.subprocess.run", fake_run
    )

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", headers=_headers(), json=_send_payload())
        health = client.get("/health")

    payload = json.loads(captured["args"][4])
    assert captured["args"][:4] == [
        str(tmp_path / "wecom-cli"),
        "msg",
        "send_message",
        "--json",
    ]
    assert payload == {
        "chat_type": 2,
        "chatid": "wr-external-room-001",
        "msgtype": "text",
        "text": {"content": "开庭提醒：明日上午九点开庭。"},
    }
    assert captured["env"]["WECOM_CLI_CONFIG_DIR"] == str(
        tmp_path / "wecom-cli-config"
    )
    assert captured["shell"] is False
    assert response.json()["data"] == {
        "isSendSuccess": 1,
        "toId": "wr-external-room-001",
        "transport": "official_cli",
        "msgServerId": "msg-001",
    }
    assert health.json()["driver"]["message_capability"] == "granted"


def test_official_cli_probe_reports_server_side_permission_denial(
    monkeypatch, tmp_path
):
    _configure_gateway(monkeypatch, tmp_path, backend="official_cli")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args,
            1,
            stdout="",
            stderr="Error: 当前企业暂不支持授权机器人「消息」使用权限\n",
        )

    monkeypatch.setattr(
        "wecom_protocol_gateway.official_cli.subprocess.run", fake_run
    )

    with TestClient(app) as client:
        probe = client.post("/api/qw/capabilities/probe", headers=_headers())
        send = client.post("/api/qw/doApi", headers=_headers(), json=_send_payload())
        health = client.get("/health")

    assert probe.json()["code"] == 5001
    assert "服务端未向当前企业开放 msg 能力" in probe.json()["msg"]
    assert probe.json()["data"]["message_capability"] == "denied"
    assert send.json()["code"] == 5001
    assert health.json()["driver"]["message_capability"] == "denied"


def test_official_cli_driver_rejects_unsupported_room_management(
    monkeypatch, tmp_path
):
    _configure_gateway(monkeypatch, tmp_path, backend="official_cli")
    payload = {
        "method": "/room/modifyRoomName",
        "params": {
            "guid": "device-zhihe-001",
            "roomId": "zhihe-legal",
            "name": "致和法务执行群",
        },
    }

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", headers=_headers(), json=payload)

    assert response.json()["code"] == 5001
    assert "不支持设备登录或修改群名" in response.json()["msg"]


def test_callback_is_encrypted_and_deduplicated(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path)
    callback = {
        "code": 0,
        "data": [
            {
                "guid": "device-zhihe-001",
                "cmd": 15000,
                "seq": 123,
                "msgUniqueIdentifier": "msg-unique-001",
                "content": "这段敏感消息不能明文落盘",
            }
        ],
    }

    with TestClient(app) as client:
        first = client.post("/callbacks/upstream", json=callback)
        second = client.post("/callbacks/upstream", json=callback)
        events = client.get("/api/qw/events", headers=_headers())

    assert first.json()["accepted"] == 1
    assert second.json()["duplicates"] == 1
    assert len(events.json()["data"]) == 1
    assert events.json()["data"][0]["status"] == "pending"

    connection = sqlite3.connect(tmp_path / "protocol-gateway.db")
    stored_payload = connection.execute(
        "SELECT payload FROM callback_events LIMIT 1"
    ).fetchone()[0]
    connection.close()
    assert "这段敏感消息".encode("utf-8") not in stored_payload


def test_gateway_requires_api_token(monkeypatch, tmp_path):
    _configure_gateway(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/api/qw/doApi", json=_send_payload())

    assert response.status_code == 401
