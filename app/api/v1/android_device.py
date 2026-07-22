from fastapi import APIRouter, Depends, Response

from app.adapters.android_device_control import (
    AndroidDeviceControl,
    AndroidDeviceControlError,
)
from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.schemas.android_device import (
    AndroidKeyeventRequest,
    AndroidSwipeRequest,
    AndroidTapRequest,
    AndroidTextRequest,
    SenderCameraPermissionRequest,
    SenderIdentityVerificationRequest,
    SenderPhoneLoginRequest,
    SenderVerificationCodeRequest,
)

router = APIRouter(
    prefix="/legal/android-device",
    tags=["legal-android-device"],
)


def _admin_operator(
    operator_info: dict[str, object] = Depends(get_current_operator),
) -> dict[str, object]:
    if operator_info.get("role") != "admin":
        raise_fail("仅管理员可以控制发送设备", code=403, status_code=403)
    return operator_info


def _control() -> AndroidDeviceControl:
    settings = get_settings()
    if not settings.wecom_android_control_enabled:
        raise_fail("Android 设备控制未启用", code=1503, status_code=503)
    return AndroidDeviceControl(
        serial=settings.wecom_android_serial,
        adb_binary=settings.wecom_android_adb_binary,
        timeout_seconds=settings.wecom_android_control_timeout_seconds,
    )


def _run_action(action) -> None:
    try:
        action()
    except ValueError as exc:
        raise_fail(str(exc), code=1422, status_code=422)
    except AndroidDeviceControlError as exc:
        raise_fail(str(exc), code=1503, status_code=503)


@router.get("/status", dependencies=[Depends(_admin_operator)])
def get_android_device_status():
    try:
        status = _control().status()
    except (AndroidDeviceControlError, ValueError) as exc:
        raise_fail(str(exc), code=1503, status_code=503)
    return ok("查询成功", status)


@router.get("/screenshot", dependencies=[Depends(_admin_operator)])
def get_android_device_screenshot() -> Response:
    try:
        screenshot = _control().screenshot()
    except (AndroidDeviceControlError, ValueError) as exc:
        raise_fail(str(exc), code=1503, status_code=503)
    return Response(
        content=screenshot,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/login/status", dependencies=[Depends(_admin_operator)])
def get_sender_login_status():
    try:
        status = _control().sender_login_status()
    except (AndroidDeviceControlError, ValueError) as exc:
        raise_fail(str(exc), code=1503, status_code=503)
    return ok("查询成功", status)


@router.post("/login/open", dependencies=[Depends(_admin_operator)])
def open_sender_login():
    _run_action(lambda: _control().open_sender_login())
    return ok("企业微信登录已打开")


@router.post("/login/phone", dependencies=[Depends(_admin_operator)])
def submit_sender_phone(payload: SenderPhoneLoginRequest):
    _run_action(lambda: _control().submit_sender_phone(payload.phone))
    return ok("手机号已提交")


@router.post("/login/agreement", dependencies=[Depends(_admin_operator)])
def accept_sender_login_agreement():
    _run_action(lambda: _control().accept_sender_login_agreement())
    return ok("已确认企业微信软件许可与隐私政策")


@router.post("/login/verification-code", dependencies=[Depends(_admin_operator)])
def submit_sender_verification_code(payload: SenderVerificationCodeRequest):
    _run_action(
        lambda: _control().submit_sender_verification_code(
            payload.verification_code
        )
    )
    return ok("验证码已提交")


@router.post("/login/identity", dependencies=[Depends(_admin_operator)])
def submit_sender_identity(payload: SenderIdentityVerificationRequest):
    _run_action(
        lambda: _control().submit_sender_identity_number(
            payload.identity_number
        )
    )
    return ok("身份信息已提交至企业微信官方验证页")


@router.post("/login/refresh-qr", dependencies=[Depends(_admin_operator)])
def refresh_sender_qr_code():
    _run_action(lambda: _control().refresh_sender_qr_code())
    return ok("二维码已刷新")


@router.post("/login/face-verification/start", dependencies=[Depends(_admin_operator)])
def start_sender_face_verification():
    _run_action(lambda: _control().start_sender_face_verification())
    return ok("已进入企业微信人脸识别流程")


@router.post("/login/camera-permission", dependencies=[Depends(_admin_operator)])
def grant_sender_camera_permission(payload: SenderCameraPermissionRequest):
    _run_action(
        lambda: _control().grant_sender_camera_permission(
            payload.permission_mode
        )
    )
    return ok("企业微信相机权限已授权")


@router.post("/tap", dependencies=[Depends(_admin_operator)])
def tap_android_device(payload: AndroidTapRequest):
    _run_action(lambda: _control().tap(payload.x, payload.y))
    return ok("点击成功")


@router.post("/swipe", dependencies=[Depends(_admin_operator)])
def swipe_android_device(payload: AndroidSwipeRequest):
    _run_action(
        lambda: _control().swipe(
            start_x=payload.start_x,
            start_y=payload.start_y,
            end_x=payload.end_x,
            end_y=payload.end_y,
            duration_ms=payload.duration_ms,
        )
    )
    return ok("滑动成功")


@router.post("/input-text", dependencies=[Depends(_admin_operator)])
def input_android_device_text(payload: AndroidTextRequest):
    _run_action(lambda: _control().input_text(payload.input_text))
    return ok("输入成功")


@router.post("/keyevent", dependencies=[Depends(_admin_operator)])
def send_android_device_keyevent(payload: AndroidKeyeventRequest):
    _run_action(lambda: _control().keyevent(payload.key))
    return ok("按键成功")
