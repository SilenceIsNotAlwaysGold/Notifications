import subprocess
import zipfile
from pathlib import Path

import pytest

from wecom_sender_sidecar.android_device import (
    AndroidDeviceError,
    AndroidDeviceManager,
    inspect_apk_abis,
)
from wecom_sender_sidecar.device_cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_inspect_apk_abis_detects_native_architectures(tmp_path):
    apk = tmp_path / "wecom.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("AndroidManifest.xml", b"manifest")
        archive.writestr("lib/arm64-v8a/libwecom.so", b"binary")
        archive.writestr("lib/armeabi-v7a/libwecom.so", b"binary")

    assert inspect_apk_abis(apk) == ["arm64-v8a", "armeabi-v7a"]


def test_install_apk_blocks_incompatible_device_abi(monkeypatch, tmp_path):
    apk = tmp_path / "wecom.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("lib/arm64-v8a/libwecom.so", b"binary")

    manager = AndroidDeviceManager(serial="127.0.0.1:5555")
    monkeypatch.setattr(manager, "device_abis", lambda: ["x86_64", "x86"])

    with pytest.raises(AndroidDeviceError, match="APK ABI"):
        manager.install_apk(apk)


def test_preflight_reports_all_android_automation_checks(monkeypatch):
    manager = AndroidDeviceManager(serial="127.0.0.1:5555")
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")

    def fake_run(args):
        command = tuple(args)
        responses = {
            ("connect", "127.0.0.1:5555"): "already connected to 127.0.0.1:5555",
            ("-s", "127.0.0.1:5555", "get-state"): "device",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "getprop",
                "sys.boot_completed",
            ): "1",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "getprop",
                "ro.build.version.sdk",
            ): "31",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "getprop",
                "ro.product.cpu.abilist",
            ): "arm64-v8a,armeabi-v7a",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "settings",
                "get",
                "secure",
                "enabled_accessibility_services",
            ): (
                "cn.zhihe.legal.sender/"
                "cn.zhihe.legal.sender.automation.WeComAccessibilityService"
            ),
            (
                "-s",
                "127.0.0.1:5555",
                "reverse",
                "--list",
            ): "127.0.0.1:5555 tcp:8092 tcp:8092",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "pm",
                "path",
                "com.tencent.wework",
            ): "package:/data/app/com.tencent.wework/base.apk",
            (
                "-s",
                "127.0.0.1:5555",
                "shell",
                "pm",
                "path",
                "cn.zhihe.legal.sender",
            ): "package:/data/app/cn.zhihe.legal.sender/base.apk",
        }
        return responses[command]

    monkeypatch.setattr(manager, "_run", fake_run)

    report = manager.preflight()

    assert report["automation_ready"] is True
    assert all(report["checks"].values())
    assert report["device"]["sdk"] == 31
    assert report["device"]["abis"] == ["arm64-v8a", "armeabi-v7a"]
    assert "企业微信通知账号已登录" in report["manual_checks"]


def test_configure_runtime_preserves_existing_accessibility_services(monkeypatch):
    manager = AndroidDeviceManager(serial="emulator-5554")
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[-4:] == [
            "settings",
            "get",
            "secure",
            "enabled_accessibility_services",
        ]:
            return "com.example/.ExistingService"
        return ""

    monkeypatch.setattr(manager, "_run", fake_run)

    result = manager.configure_runtime(
        accessibility_component=(
            "cn.zhihe.legal.sender/"
            "cn.zhihe.legal.sender.automation.WeComAccessibilityService"
        ),
        companion_package="cn.zhihe.legal.sender",
    )

    put_command = next(
        call
        for call in calls
        if "enabled_accessibility_services" in call and "put" in call
    )
    assert "com.example/.ExistingService" in put_command[-1]
    assert (
        "cn.zhihe.legal.sender/"
        "cn.zhihe.legal.sender.automation.WeComAccessibilityService"
        in put_command[-1]
    )
    assert ["-s", "emulator-5554", "reverse", "tcp:8092", "tcp:8092"] in calls
    assert [
        "-s",
        "emulator-5554",
        "shell",
        "am",
        "start",
        "-n",
        "cn.zhihe.legal.sender/.MainActivity",
    ] in calls
    assert result["companion_launched"] is True
    assert result["companion_activity"] == "cn.zhihe.legal.sender/.MainActivity"


def test_adb_invocation_never_uses_shell(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="device\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    manager = AndroidDeviceManager(serial="emulator-5554")

    assert manager._run_device(["get-state"]) == "device"
    assert captured["args"] == ["adb", "-s", "emulator-5554", "get-state"]
    assert captured["shell"] is False


def test_device_cli_returns_nonzero_for_invalid_serial(capsys):
    exit_code = main(["--serial", "bad;serial", "check"])

    assert exit_code == 1
    assert "serial 格式不正确" in capsys.readouterr().out


def test_android_compose_override_binds_control_ports_to_loopback():
    compose = (PROJECT_ROOT / "docker-compose.android.yml").read_text(
        encoding="utf-8"
    )

    assert '"127.0.0.1:${WECOM_SENDER_PORT:-8092}:8092"' in compose
    assert '"127.0.0.1:${WECOM_ANDROID_ADB_PORT:-5555}:5555"' in compose
    assert "0.0.0.0" not in compose


def test_android_sender_recovery_assets_restore_runtime_without_secrets():
    script = (PROJECT_ROOT / "scripts" / "ensure_android_sender.sh").read_text(
        encoding="utf-8"
    )
    service = (
        PROJECT_ROOT / "deploy" / "legal-wecom-android-sender.service"
    ).read_text(encoding="utf-8")

    assert "WECOM_ANDROID_SERIAL" in script
    assert "device_cli" in script
    assert "start-foreground-service" not in script
    assert ".gateway.GatewayService" not in script
    assert "LaunchSplashActivity" in script
    assert "ADMIN_API_KEYS" not in script
    assert "EnvironmentFile=" not in service
    assert "ensure_android_sender.sh" in service
    assert "Restart=on-failure" in service
