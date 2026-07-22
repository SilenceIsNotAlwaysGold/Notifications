import json
import subprocess

import pytest
from fastapi import HTTPException

from app.adapters.android_device_control import (
    AndroidDeviceControl,
    AndroidDeviceControlError,
)
from app.api.v1.android_device import _admin_operator
from app.core.config import get_settings
from app.middleware.audit_middleware import (
    AUDIT_EXCLUDED_ENDPOINTS,
    OperationAuditMiddleware,
)
from app.utils.china_identity import is_valid_china_identity_number


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("11010519491231002X", True),
        ("11010519491231002x", True),
        ("130503670401001", True),
        ("11010519491331002X", False),
        ("110105194912310021", False),
        ("00000019491231002X", False),
    ],
)
def test_china_identity_number_validation(value, expected):
    assert is_valid_china_identity_number(value) is expected


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


def test_sender_login_status_and_phone_flow_are_stage_gated(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(
        control,
        "_run_text",
        lambda args: (
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.login.controller.LoginVeryfyStep1Activity t12}"
        ),
    )
    taps = []
    values = []
    monkeypatch.setattr(control, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr(control, "input_text", values.append)

    assert control.sender_login_status()["stage"] == "phone"
    control.submit_sender_phone("13800138000")

    assert taps == [(985, 466), (480, 466), (540, 680)]
    assert values == ["13800138000"]


def test_sender_login_status_reports_qr_identity_face_check_and_logged_in(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    outputs = iter(
        [
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.common.web.JsWebActivity t12}",
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.setting.controller.UserRealNameCardIdCheckActivity t12}",
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.setting.controller.IdentityRecognitionAgreementActivity t12}",
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.foundation.views.WwMainActivity t12}",
        ]
    )
    monkeypatch.setattr(control, "_run_text", lambda args: next(outputs))

    assert control.sender_login_status()["stage"] == "qr_code"
    assert control.sender_login_status()["stage"] == "identity_verification"
    assert control.sender_login_status()["stage"] == "face_verification"
    assert control.sender_login_status()["stage"] == "logged_in"


@pytest.mark.parametrize(
    ("resource_id", "expected_stage", "expected_online"),
    [
        ("com.tencent.wework:id/kls", "qr_code", False),
        ("com.tencent.wework:id/dh0", "verification_code", False),
        ("com.tencent.wework:id/avu", "login_pending", False),
    ],
)
def test_sender_login_status_reports_android_pad_login_stages(
    monkeypatch,
    resource_id,
    expected_stage,
    expected_online,
):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5556")
    monkeypatch.setattr(
        control,
        "_foreground_component",
        lambda: (
            "com.tencent.wework",
            "com.tencent.wework.login.controller.LoginQrCodeForAndroidPad",
        ),
    )
    monkeypatch.setattr(control, "_visible_ui_resources", lambda: {resource_id})

    assert control.sender_login_status() == {
        "stage": expected_stage,
        "online": expected_online,
    }


def test_sender_pad_verification_uses_pad_dialog_coordinates(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5556")
    monkeypatch.setattr(
        control,
        "sender_login_status",
        lambda: {"stage": "verification_code", "online": False},
    )
    monkeypatch.setattr(
        control,
        "_foreground_component",
        lambda: (
            "com.tencent.wework",
            "com.tencent.wework.login.controller.LoginQrCodeForAndroidPad",
        ),
    )
    taps = []
    values = []
    monkeypatch.setattr(control, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr(control, "input_text", values.append)

    control.submit_sender_verification_code("791452")

    assert taps == [(540, 668), (695, 755)]
    assert values == ["791452"]


def test_sender_login_status_reports_camera_permission(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(
        control,
        "_run_text",
        lambda args: (
            "mFocusedApp=ActivityRecord{1 u0 com.android.permissioncontroller/"
            ".permission.ui.GrantPermissionsActivity t12}"
        ),
    )

    assert control.sender_login_status()["stage"] == "camera_permission"


@pytest.mark.parametrize(
    ("has_error", "expected_stage"),
    [(True, "face_camera_error"), (False, "face_capture")],
)
def test_sender_login_status_reports_face_capture_state(
    monkeypatch,
    has_error,
    expected_stage,
):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(
        control,
        "_foreground_component",
        lambda: (
            "com.tencent.wework",
            "com.tencent.could.huiyansdk.activitys.MainAuthActivity",
        ),
    )
    monkeypatch.setattr(control, "_has_ui_resource", lambda resource_id: has_error)

    assert control.sender_login_status()["stage"] == expected_stage


@pytest.mark.parametrize(
    ("permission_mode", "expected_y"),
    [("once", 1068), ("while_using", 918)],
)
def test_sender_camera_permission_uses_selected_mode(
    monkeypatch,
    permission_mode,
    expected_y,
):
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    taps = []
    monkeypatch.setattr(
        control,
        "sender_login_status",
        lambda: {"stage": "camera_permission", "online": True},
    )
    monkeypatch.setattr(control, "tap", lambda x, y: taps.append((x, y)))

    control.grant_sender_camera_permission(permission_mode)

    assert taps == [(540, expected_y)]


def test_sender_face_verification_accepts_agreement(monkeypatch):
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    taps = []
    monkeypatch.setattr(
        control,
        "sender_login_status",
        lambda: {"stage": "face_verification", "online": True},
    )
    monkeypatch.setattr(control, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    control.start_sender_face_verification()

    assert taps == [(72, 984), (540, 1175)]


def test_sender_identity_number_is_forwarded_only_on_identity_stage(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(
        control,
        "_run_text",
        lambda args: (
            "mFocusedApp=ActivityRecord{1 u0 "
            "com.tencent.wework/.setting.controller.UserRealNameCardIdCheckActivity t12}"
        ),
    )
    actions = []
    monkeypatch.setattr(
        control,
        "tap",
        lambda x, y: actions.append(("tap", x, y)),
    )
    monkeypatch.setattr(
        control,
        "_replace_identity_number",
        lambda value: actions.append(("replace", value)),
    )
    monkeypatch.setattr(
        control,
        "keyevent",
        lambda key: actions.append(("keyevent", key)),
    )
    monkeypatch.setattr(
        control,
        "_wait_for_login_stage_change",
        lambda stage: actions.append(("wait", stage)),
    )

    monkeypatch.setattr("time.sleep", lambda seconds: None)

    control.submit_sender_identity_number("11010519491231002x")

    assert actions == [
        ("tap", 620, 995),
        ("replace", "11010519491231002X"),
        ("keyevent", "back"),
        ("tap", 540, 1150),
        ("wait", "identity_verification"),
    ]


def test_sender_identity_number_retries_until_device_value_matches(monkeypatch):
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    actions = []
    values = iter(["11010519491231002X1", "11010519491231002X"])
    monkeypatch.setattr(
        control,
        "_clear_focused_text",
        lambda: actions.append("clear"),
    )
    monkeypatch.setattr(control, "input_text", lambda value: actions.append(value))
    monkeypatch.setattr(control, "_identity_field_value", lambda: next(values))
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    control._replace_identity_number("11010519491231002X")

    assert actions == [
        "clear",
        "11010519491231002X",
        "clear",
        "11010519491231002X",
    ]


def test_sender_identity_number_fails_when_device_value_never_matches(monkeypatch):
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(control, "_clear_focused_text", lambda: None)
    monkeypatch.setattr(control, "input_text", lambda value: None)
    monkeypatch.setattr(control, "_identity_field_value", lambda: "mismatch")
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(AndroidDeviceControlError, match="未能正确写入"):
        control._replace_identity_number("11010519491231002X")


def test_sender_identity_number_reports_when_wecom_does_not_advance(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda value: f"/usr/bin/{value}")
    control = AndroidDeviceControl(serial="127.0.0.1:5555")
    monkeypatch.setattr(
        control,
        "sender_login_status",
        lambda: {"stage": "identity_verification", "online": True},
    )
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    with pytest.raises(AndroidDeviceControlError, match="未进入下一步"):
        control._wait_for_login_stage_change("identity_verification")


def test_sender_login_api_exposes_native_stage(client, monkeypatch):
    monkeypatch.setenv("WECOM_ANDROID_CONTROL_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        AndroidDeviceControl,
        "sender_login_status",
        lambda self: {"online": True, "stage": "phone"},
    )

    response = client.get("/api/v1/legal/android-device/login/status")

    assert response.status_code == 200
    assert response.json()["data"] == {"online": True, "stage": "phone"}
    monkeypatch.setattr(
        AndroidDeviceControl,
        "submit_sender_identity_number",
        lambda self, value: None,
    )
    identity = client.post(
        "/api/v1/legal/android-device/login/identity",
        json={"identity_number": "11010519491231002X"},
    )

    assert identity.status_code == 200
    monkeypatch.setattr(
        AndroidDeviceControl,
        "start_sender_face_verification",
        lambda self: None,
    )
    face = client.post(
        "/api/v1/legal/android-device/login/face-verification/start",
        json={},
    )
    assert face.status_code == 200

    invalid_identity = client.post(
        "/api/v1/legal/android-device/login/identity",
        json={"identity_number": "110105194912310021"},
    )
    assert invalid_identity.status_code == 422
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
    login_summary = middleware._request_summary(
        json.dumps(
            {
                "phone": "13800138000",
                "verification_code": "123456",
                "identity_number": "11010119900101123X",
            }
        ).encode("utf-8")
    )
    assert login_summary == {
        "json": {
            "phone": "***",
            "verification_code": "***",
            "identity_number": "***",
        }
    }
    assert (
        "GET",
        "/api/v1/legal/android-device/screenshot",
    ) in AUDIT_EXCLUDED_ENDPOINTS
