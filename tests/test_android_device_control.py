import json
import subprocess

import pytest
from fastapi import HTTPException

from app.adapters.android_device_control import AndroidDeviceControl
from app.api.v1.android_device import _admin_operator
from app.core.config import get_settings
from app.middleware.audit_middleware import (
    AUDIT_EXCLUDED_ENDPOINTS,
    OperationAuditMiddleware,
)


def test_android_device_control_uses_argument_lists_without_shell(monkeypatch):
    captured = []

    def fake_run(args, **kwargs):
        captured.append((args, kwargs))
        stdout = "" if kwargs["text"] else b"\x89PNG\r\n\x1a\nimage"
        stderr = "" if kwargs["text"] else b""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    monkeypatch.setattr("subprocess.run", fake_run)
    control = AndroidDeviceControl(serial="127.0.0.1:5555")

    control.tap(120, 240)
    control.swipe(
        start_x=120,
        start_y=800,
        end_x=120,
        end_y=300,
        duration_ms=350,
    )
    control.input_text("safe value-123")
    control.keyevent("back")
    assert control.screenshot().startswith(b"\x89PNG")

    assert all(kwargs["shell"] is False for _, kwargs in captured)
    assert [
        "adb",
        "-s",
        "127.0.0.1:5555",
        "shell",
        "input",
        "text",
        "safe%svalue-123",
    ] in [args for args, _ in captured]


@pytest.mark.parametrize(
    "value",
    ["bad;command", "line\nbreak", "中文输入", "$(whoami)"],
)
def test_android_device_control_rejects_unsafe_text(value):
    control = AndroidDeviceControl(serial="127.0.0.1:5555")

    with pytest.raises(ValueError, match="仅支持"):
        control.input_text(value)


def test_android_device_control_endpoints_return_screen_and_accept_tap(
    client,
    monkeypatch,
):
    monkeypatch.setenv("WECOM_ANDROID_CONTROL_ENABLED", "true")
    get_settings.cache_clear()
    captured = {}
    monkeypatch.setattr(
        AndroidDeviceControl,
        "status",
        lambda self: {
            "online": True,
            "state": "device",
            "width": 1080,
            "height": 1920,
        },
    )
    monkeypatch.setattr(
        AndroidDeviceControl,
        "screenshot",
        lambda self: b"\x89PNG\r\n\x1a\nimage",
    )
    monkeypatch.setattr(
        AndroidDeviceControl,
        "tap",
        lambda self, x, y: captured.update(x=x, y=y),
    )

    status = client.get("/api/v1/legal/android-device/status")
    screenshot = client.get("/api/v1/legal/android-device/screenshot")
    tapped = client.post(
        "/api/v1/legal/android-device/tap",
        json={"x": 220, "y": 440},
    )

    assert status.status_code == 200
    assert status.json()["data"]["online"] is True
    assert screenshot.status_code == 200
    assert screenshot.headers["content-type"] == "image/png"
    assert screenshot.headers["cache-control"].startswith("no-store")
    assert tapped.status_code == 200
    assert captured == {"x": 220, "y": 440}
    get_settings.cache_clear()


def test_android_device_control_is_disabled_by_default(client):
    response = client.get("/api/v1/legal/android-device/status")

    assert response.status_code == 503
    assert response.json()["message"] == "Android 设备控制未启用"


def test_android_device_control_requires_admin_role():
    with pytest.raises(HTTPException) as exc_info:
        _admin_operator({"role": "legal"})

    assert exc_info.value.status_code == 403


def test_device_text_is_masked_and_screenshot_polling_is_not_audited():
    middleware = OperationAuditMiddleware(app=None)
    summary = middleware._request_summary(
        json.dumps({"input_text": "123456"}).encode("utf-8")
    )

    assert summary == {"json": {"input_text": "***"}}
    assert (
        "GET",
        "/api/v1/legal/android-device/screenshot",
    ) in AUDIT_EXCLUDED_ENDPOINTS
