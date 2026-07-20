import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.adapters.wecom_bot import WeComBotAdapter
from app.adapters.wecomapi import WeComApiAdapter
from app.adapters.wecom_cli import WeComCliAdapter
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.wecom_archive_group import WeComArchiveGroup
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

        if mode == "wecomapi":
            protocol_room_id = self._resolve_wecomapi_room_id(group_id)
            if not protocol_room_id:
                result = {
                    "success": False,
                    "mode": "wecomapi",
                    "status_code": None,
                    "response": None,
                    "error": f"群 {group_id} 未配置 wecomapi 协议群 ID，已阻止发送",
                }
                self._log_result(group_id, content, result)
                return result
            result = WeComApiAdapter(
                base_url=effective["wecom"].get("wecomapi_base_url"),
                api_path=str(effective["wecom"].get("wecomapi_api_path") or "/wecom/finder/api"),
                token=effective["wecom"].get("wecomapi_token"),
                guid=effective["wecom"].get("wecomapi_guid"),
                timeout_seconds=int(effective["wecom"]["timeout_seconds"]),
                min_interval_seconds=float(effective["wecom"].get("wecomapi_min_interval_seconds") or 0),
                daily_limit=int(effective["wecom"].get("wecomapi_daily_limit") or 200),
                failure_threshold=int(effective["wecom"].get("wecomapi_failure_threshold") or 3),
                cooldown_seconds=int(effective["wecom"].get("wecomapi_cooldown_seconds") or 300),
            ).send_text(protocol_room_id, content)
            self._log_result(group_id, content, result)
            return result

        if mode == "wecom_cli":
            if not self._is_enabled_archive_group(group_id):
                result = {
                    "success": False,
                    "mode": "wecom_cli",
                    "status_code": None,
                    "response": None,
                    "error": f"群 {group_id} 未在归档群管理中启用，已阻止发送",
                }
                self._log_result(group_id, content, result)
                return result
            result = WeComCliAdapter(
                binary=str(effective["wecom"].get("wecom_cli_binary") or "wecom-cli"),
                config_dir=str(effective["wecom"].get("wecom_cli_config_dir") or "~/.config/wecom"),
                timeout_seconds=int(effective["wecom"].get("wecom_cli_timeout_seconds") or 35),
                min_interval_seconds=float(effective["wecom"].get("wecom_cli_min_interval_seconds") or 0),
                daily_limit=int(effective["wecom"].get("wecom_cli_daily_limit") or 200),
                group_daily_limit=int(effective["wecom"].get("wecom_cli_group_daily_limit") or 10),
                failure_threshold=int(effective["wecom"].get("wecom_cli_failure_threshold") or 3),
                cooldown_seconds=int(effective["wecom"].get("wecom_cli_cooldown_seconds") or 300),
            ).send_text(group_id, content)
            self._log_result(group_id, content, result)
            return result

        if mode == "wecom_bot":
            if not self._is_enabled_archive_group(group_id):
                result = {
                    "success": False,
                    "mode": "wecom_bot",
                    "status_code": None,
                    "response": None,
                    "error": f"群 {group_id} 未在归档群管理中启用，已阻止发送",
                }
                self._log_result(group_id, content, result)
                return result
            result = WeComBotAdapter(
                base_url=effective["wecom"].get("wecom_bot_sidecar_url"),
                token=effective["wecom"].get("wecom_bot_sidecar_token"),
                timeout_seconds=int(effective["wecom"].get("wecom_bot_timeout_seconds") or 10),
                min_interval_seconds=float(effective["wecom"].get("wecom_bot_min_interval_seconds") or 0),
                daily_limit=int(effective["wecom"].get("wecom_bot_daily_limit") or 200),
                group_daily_limit=int(effective["wecom"].get("wecom_bot_group_daily_limit") or 10),
                failure_threshold=int(effective["wecom"].get("wecom_bot_failure_threshold") or 3),
                cooldown_seconds=int(effective["wecom"].get("wecom_bot_cooldown_seconds") or 300),
            ).send_text(group_id, content)
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
                    "wecomapi_base_url": self.settings.wecomapi_base_url,
                    "wecomapi_api_path": self.settings.wecomapi_api_path,
                    "wecomapi_token": self.settings.wecomapi_token,
                    "wecomapi_guid": self.settings.wecomapi_guid,
                    "wecomapi_min_interval_seconds": self.settings.wecomapi_min_interval_seconds,
                    "wecomapi_daily_limit": self.settings.wecomapi_daily_limit,
                    "wecomapi_failure_threshold": self.settings.wecomapi_failure_threshold,
                    "wecomapi_cooldown_seconds": self.settings.wecomapi_cooldown_seconds,
                    "wecom_cli_binary": self.settings.wecom_cli_binary,
                    "wecom_cli_config_dir": self.settings.wecom_cli_config_dir,
                    "wecom_cli_timeout_seconds": self.settings.wecom_cli_timeout_seconds,
                    "wecom_cli_min_interval_seconds": self.settings.wecom_cli_min_interval_seconds,
                    "wecom_cli_daily_limit": self.settings.wecom_cli_daily_limit,
                    "wecom_cli_group_daily_limit": self.settings.wecom_cli_group_daily_limit,
                    "wecom_cli_failure_threshold": self.settings.wecom_cli_failure_threshold,
                    "wecom_cli_cooldown_seconds": self.settings.wecom_cli_cooldown_seconds,
                    "wecom_bot_sidecar_url": self.settings.wecom_bot_sidecar_url,
                    "wecom_bot_sidecar_token": self.settings.wecom_bot_sidecar_token,
                    "wecom_bot_timeout_seconds": self.settings.wecom_bot_timeout_seconds,
                    "wecom_bot_min_interval_seconds": self.settings.wecom_bot_min_interval_seconds,
                    "wecom_bot_daily_limit": self.settings.wecom_bot_daily_limit,
                    "wecom_bot_group_daily_limit": self.settings.wecom_bot_group_daily_limit,
                    "wecom_bot_failure_threshold": self.settings.wecom_bot_failure_threshold,
                    "wecom_bot_cooldown_seconds": self.settings.wecom_bot_cooldown_seconds,
                },
                "feature_flags": {"enable_wecom_send": True},
            }
        db = SessionLocal()
        try:
            return TenantSettingsService(db).get_effective_settings(tenant_id)
        finally:
            db.close()

    @staticmethod
    def _resolve_wecomapi_room_id(group_id: str) -> str | None:
        db = SessionLocal()
        try:
            group = db.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == group_id))
            if not group or group.status != "enabled":
                return None
            return group.wecomapi_room_id
        finally:
            db.close()

    @staticmethod
    def _is_enabled_archive_group(group_id: str) -> bool:
        db = SessionLocal()
        try:
            group = db.scalar(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == group_id))
            return bool(group and group.status == "enabled")
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
            "企业微信发送结果 mode=%s group_id=%s content_length=%s success=%s",
            result["mode"],
            group_id,
            len(content),
            result["success"],
        )
