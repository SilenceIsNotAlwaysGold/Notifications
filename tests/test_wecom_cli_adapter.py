import json
import subprocess

from app.adapters.wecom_cli import WeComCliAdapter
from app.adapters.wecom_message import WeComMessageAdapter
from app.core.config import get_settings
from app.models.wecom_archive_group import WeComArchiveGroup


def _configure_cli(monkeypatch, tmp_path, *, group_daily_limit: int = 10) -> None:
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_cli")
    monkeypatch.setenv("WECOM_CLI_BINARY", "/usr/local/bin/wecom-cli")
    monkeypatch.setenv("WECOM_CLI_CONFIG_DIR", str(tmp_path / "wecom-config"))
    monkeypatch.setenv("WECOM_CLI_TIMEOUT_SECONDS", "35")
    monkeypatch.setenv("WECOM_CLI_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("WECOM_CLI_DAILY_LIMIT", "200")
    monkeypatch.setenv("WECOM_CLI_GROUP_DAILY_LIMIT", str(group_daily_limit))
    monkeypatch.setenv("WECOM_CLI_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("WECOM_CLI_COOLDOWN_SECONDS", "300")
    get_settings.cache_clear()
    WeComCliAdapter.reset_safety_state()


def _successful_cli_result() -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "test",
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"errcode": 0, "errmsg": "ok"}),
                    }
                ]
            },
        }
    )


def test_wecom_cli_send_uses_official_archive_room_id(db_session, monkeypatch, tmp_path):
    _configure_cli(monkeypatch, tmp_path)
    db_session.add(
        WeComArchiveGroup(
            room_id="wrOfficialGroup001",
            display_name="致和法务执行群",
            status="enabled",
        )
    )
    db_session.commit()
    captured = {}

    def fake_run(args, **kwargs):
        captured.update({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, 0, stdout=_successful_cli_result(), stderr="")

    monkeypatch.setattr("app.adapters.wecom_cli.subprocess.run", fake_run)

    result = WeComMessageAdapter().send_text("wrOfficialGroup001", "开庭提醒")

    assert result["success"] is True
    assert result["mode"] == "wecom_cli"
    assert captured["args"][:4] == [
        "/usr/local/bin/wecom-cli",
        "msg",
        "send_message",
        "--json",
    ]
    assert json.loads(captured["args"][4]) == {
        "chat_type": 2,
        "chatid": "wrOfficialGroup001",
        "msgtype": "text",
        "text": {"content": "开庭提醒"},
    }
    assert captured["env"]["WECOM_CLI_CONFIG_DIR"] == str(tmp_path / "wecom-config")
    assert captured["shell"] is False


def test_wecom_cli_send_to_disabled_group_is_blocked(db_session, monkeypatch, tmp_path):
    _configure_cli(monkeypatch, tmp_path)
    db_session.add(
        WeComArchiveGroup(
            room_id="wrOfficialGroup002",
            display_name="未启用群",
            status="discovered",
        )
    )
    db_session.commit()
    called = False

    def fake_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("disabled group must not invoke CLI")

    monkeypatch.setattr("app.adapters.wecom_cli.subprocess.run", fake_run)

    result = WeComMessageAdapter().send_text("wrOfficialGroup002", "缴费提醒")

    assert result["success"] is False
    assert "未在归档群管理中启用" in result["error"]
    assert called is False


def test_wecom_cli_business_error_is_reported(monkeypatch, tmp_path):
    _configure_cli(monkeypatch, tmp_path)

    def fake_run(args, **kwargs):
        stdout = json.dumps({"errcode": 86008, "errmsg": "chat not found"})
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr("app.adapters.wecom_cli.subprocess.run", fake_run)
    adapter = WeComCliAdapter(
        binary="wecom-cli",
        config_dir=str(tmp_path / "wecom-config"),
        timeout_seconds=35,
        min_interval_seconds=0,
        daily_limit=200,
        group_daily_limit=10,
        failure_threshold=3,
        cooldown_seconds=300,
    )

    result = adapter.send_text("wrOfficialGroup003", "提醒")

    assert result["success"] is False
    assert "errcode=86008" in result["error"]


def test_wecom_cli_enforces_utf8_byte_and_per_group_limits(monkeypatch, tmp_path):
    _configure_cli(monkeypatch, tmp_path, group_daily_limit=1)
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args, 0, stdout=_successful_cli_result(), stderr="")

    monkeypatch.setattr("app.adapters.wecom_cli.subprocess.run", fake_run)
    adapter = WeComCliAdapter(
        binary="wecom-cli",
        config_dir=str(tmp_path / "wecom-config"),
        timeout_seconds=35,
        min_interval_seconds=0,
        daily_limit=200,
        group_daily_limit=1,
        failure_threshold=3,
        cooldown_seconds=300,
    )

    assert adapter.send_text("wrOfficialGroup004", "第一次提醒")["success"] is True
    blocked = adapter.send_text("wrOfficialGroup004", "第二次提醒")
    oversized = adapter.send_text("wrOfficialGroup005", "法" * 683)

    assert "每日发送上限 1" in blocked["error"]
    assert "2048 字节" in oversized["error"]
    assert calls == 1
