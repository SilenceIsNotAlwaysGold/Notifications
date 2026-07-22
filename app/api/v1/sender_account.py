from fastapi import APIRouter, Depends

from app.adapters.wecom_protocol_account import (
    WeComProtocolAccount,
    WeComProtocolAccountError,
)
from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.schemas.android_device import SenderProtocolVerificationRequest

router = APIRouter(prefix="/legal/sender-account", tags=["legal-sender-account"])


def _admin_operator(
    operator_info: dict[str, object] = Depends(get_current_operator),
) -> dict[str, object]:
    if operator_info.get("role") != "admin":
        raise_fail("仅管理员可以管理发送账号", code=403, status_code=403)
    return operator_info


def _account() -> WeComProtocolAccount:
    settings = get_settings()
    return WeComProtocolAccount(
        base_url=settings.wecom_protocol_account_base_url,
        api_path=settings.wecom_protocol_account_api_path,
        token=settings.wecom_protocol_account_token,
        guid=settings.wecom_protocol_account_guid,
        timeout_seconds=settings.wecom_timeout_seconds,
    )


def _run(action):
    try:
        return action()
    except ValueError as exc:
        raise_fail(str(exc), code=1422, status_code=422)
    except WeComProtocolAccountError as exc:
        raise_fail(str(exc), code=1503, status_code=503)


@router.get("/status", dependencies=[Depends(_admin_operator)])
def get_sender_account_status():
    if get_settings().wecom_account_login_mode == "android":
        return ok("查询成功", {"backend": "android"})
    return ok("查询成功", _run(_account().status))


@router.post("/login/start", dependencies=[Depends(_admin_operator)])
def start_sender_account_login():
    _require_protocol_mode()
    return ok("登录二维码已生成", _run(_account().start_login))


@router.get("/login/poll", dependencies=[Depends(_admin_operator)])
def poll_sender_account_login():
    _require_protocol_mode()
    return ok("查询成功", _run(_account().poll_login))


@router.post("/login/verify", dependencies=[Depends(_admin_operator)])
def verify_sender_account_login(payload: SenderProtocolVerificationRequest):
    _require_protocol_mode()
    return ok(
        "登录验证已提交",
        _run(lambda: _account().verify_login(payload.verification_value)),
    )


@router.post("/logout", dependencies=[Depends(_admin_operator)])
def logout_sender_account():
    _require_protocol_mode()
    return ok("发送账号已退出", _run(_account().logout))


def _require_protocol_mode() -> None:
    if get_settings().wecom_account_login_mode != "protocol":
        raise_fail("发送账号当前使用 Android 登录通道", code=1409, status_code=409)
