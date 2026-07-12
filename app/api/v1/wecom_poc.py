import logging
from typing import Any

import httpx
from fastapi import APIRouter

from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.config import get_settings
from app.schemas.legal import WeComArchiveCheckIn, WeComArchiveCheckOut, WeComPocSendTestIn, WeComPocSendTestOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal/wecom-poc", tags=["legal-wecom-poc"])


@router.post("/send-test")
def send_wecom_poc_test(payload: WeComPocSendTestIn):
    webhook_url = (payload.webhook_url or "").strip()
    if not webhook_url:
        raise_fail("webhook_url 不能为空", code=1601)

    request_payload = {
        "msgtype": "text",
        "text": {
            "content": payload.content,
            "mentioned_list": payload.mentioned_userids,
            "mentioned_mobile_list": payload.mentioned_mobiles,
        },
    }
    try:
        response = httpx.post(webhook_url, json=request_payload, timeout=get_settings().wecom_timeout_seconds)
        response_payload = _parse_response(response)
        errcode = _int_or_none(response_payload.get("errcode"))
        errmsg = response_payload.get("errmsg")
        success = response.status_code < 400 and errcode in (None, 0)
        data = WeComPocSendTestOut(
            success=success,
            errcode=errcode,
            errmsg=str(errmsg) if errmsg is not None else None,
            status_code=response.status_code,
            error=None if success else _error_message(response.status_code, response_payload),
        )
        logger.info("企业微信 POC 发送测试完成 status_code=%s success=%s", response.status_code, success)
        return ok("发送成功" if success else "发送失败", data)
    except Exception as exc:
        logger.exception("企业微信 POC 发送测试请求失败")
        data = WeComPocSendTestOut(success=False, error=str(exc))
        return ok("发送失败", data)


@router.post("/archive-check")
def check_wecom_archive_config(payload: WeComArchiveCheckIn):
    data = _check_archive_payload(payload)
    return ok("配置检查完成", data)


@router.get("/archive-check/current")
def check_current_wecom_archive_config():
    settings = get_settings()
    payload = WeComArchiveCheckIn(
        corp_id=settings.wecom_corp_id,
        archive_secret=settings.wecom_archive_secret,
        private_key_path=settings.wecom_archive_private_key_path,
        public_key_ver=settings.wecom_archive_public_key_ver,
        sidecar_url=settings.wecom_archive_sidecar_url,
    )
    data = _check_archive_payload(payload)
    return ok("当前配置检查完成", data)


def _check_archive_payload(payload: WeComArchiveCheckIn) -> WeComArchiveCheckOut:
    missing_fields = []
    if not payload.corp_id:
        missing_fields.append("corp_id")
    if not payload.archive_secret:
        missing_fields.append("archive_secret")
    if not payload.private_key and not payload.private_key_path:
        missing_fields.append("private_key_or_private_key_path")
    if not payload.public_key_ver:
        missing_fields.append("public_key_ver")
    if not payload.sidecar_url:
        missing_fields.append("sidecar_url")

    warnings = [
        "真实拉取需要企业微信会话内容存档官方 SDK 或 SDK sidecar，系统不会使用非官方 hook",
        "尚未验证客户是否已开通会话内容存档",
        "尚未验证外部群是否在存档范围内",
        "尚未验证参与群聊员工是否在存档范围内",
        "尚未验证图片、文件、PDF 等媒体是否允许拉取",
    ]
    return WeComArchiveCheckOut(ready=not missing_fields, missing_fields=missing_fields, warnings=warnings)


def _parse_response(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except ValueError:
        return {"text": response.text}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _error_message(status_code: int, response_payload: dict[str, Any]) -> str:
    if status_code >= 400:
        return f"企业微信 webhook HTTP {status_code}"
    errcode = response_payload.get("errcode")
    errmsg = response_payload.get("errmsg") or "企业微信返回错误"
    return f"企业微信返回 errcode={errcode}, errmsg={errmsg}"
