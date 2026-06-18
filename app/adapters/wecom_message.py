import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.tenant_settings_service import TenantSettingsService

logger = logging.getLogger(__name__)


class WeComMessageAdapter:
    def __init__(self, webhook_url: str | None = None) -> None:
        self.settings = get_settings()
        self.webhook_url = webhook_url or self.settings.wecom_webhook_url
        self.mode = self.settings.wecom_send_mode

    def send_text(
        self,
        group_id: str,
        content: str,
        mentioned_userids: list[str] | None = None,
        mentioned_mobiles: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        effective = self._effective_wecom_settings(tenant_id)
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": mentioned_userids or [],
                "mentioned_mobile_list": mentioned_mobiles or [],
            },
        }
        if not effective["feature_flags"].get("enable_wecom_send", True):
            result = {
                "success": False,
                "skipped": True,
                "mode": effective["wecom"]["send_mode"],
                "status_code": None,
                "response": {"skipped": True, "reason": "tenant_feature_disabled"},
                "error": "租户已关闭企业微信发送",
            }
            self._log_result(group_id, content, result)
            return result

        mode = effective["wecom"]["send_mode"]
        webhook_url = self.webhook_url if tenant_id is None and self.webhook_url else effective["wecom"].get("webhook_url")
        timeout_seconds = effective["wecom"]["timeout_seconds"]

        if mode == "mock":
            response_payload = {"mock": True, "payload": payload}
            if tenant_id is not None:
                response_payload["tenant_settings_source"] = effective["source"]
            result = {
                "success": True,
                "mode": "mock",
                "status_code": None,
                "response": response_payload,
                "error": None,
            }
            self._log_result(group_id, content, result)
            return result

        if not webhook_url:
            result = {
                "success": False,
                "mode": "webhook",
                "status_code": None,
                "response": None,
                "error": "WECOM_WEBHOOK_URL 为空",
            }
            self._log_result(group_id, content, result)
            return result

        try:
            response = httpx.post(
                webhook_url,
                json=payload,
                timeout=timeout_seconds,
            )
            response_payload = self._parse_response(response)
            error = self._response_error(response.status_code, response_payload)
            result = {
                "success": error is None,
                "mode": "webhook",
                "status_code": response.status_code,
                "response": response_payload,
                "error": error,
            }
        except Exception as exc:
            result = {
                "success": False,
                "mode": "webhook",
                "status_code": None,
                "response": None,
                "error": str(exc),
            }
        self._log_result(group_id, content, result)
        return result

    def _effective_wecom_settings(self, tenant_id: str | None) -> dict[str, Any]:
        if tenant_id is None:
            return {
                "source": "global",
                "wecom": {
                    "send_mode": self.mode,
                    "webhook_url": self.webhook_url,
                    "timeout_seconds": self.settings.wecom_timeout_seconds,
                    "max_retry": self.settings.wecom_max_retry,
                },
                "feature_flags": {"enable_wecom_send": True},
            }
        db = SessionLocal()
        try:
            return TenantSettingsService(db).get_effective_settings(tenant_id)
        finally:
            db.close()

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                return parsed
            return {"data": parsed}
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _response_error(status_code: int, response_payload: dict[str, Any]) -> str | None:
        if status_code >= 400:
            return f"企业微信 webhook HTTP {status_code}"
        errcode = response_payload.get("errcode")
        if errcode not in (None, 0):
            errmsg = response_payload.get("errmsg") or "企业微信返回错误"
            return f"企业微信返回 errcode={errcode}, errmsg={errmsg}"
        return None

    @staticmethod
    def _log_result(group_id: str, content: str, result: dict[str, Any]) -> None:
        logger.info(
            "企业微信发送结果 mode=%s group_id=%s content_preview=%s success=%s",
            result["mode"],
            group_id,
            content[:100],
            result["success"],
        )
