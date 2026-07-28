import logging
from typing import Any

from sqlalchemy import select

from app.adapters.wecomapi import WeComApiAdapter
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.contact import Contact, ContactGroup
from app.services.tenant_settings_service import TenantSettingsService

logger = logging.getLogger(__name__)


class WeComMessageAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
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
                token_header=str(effective["wecom"].get("wecomapi_token_header") or "WECOM-TOKEN"),
                guid=effective["wecom"].get("wecomapi_guid"),
                timeout_seconds=int(effective["wecom"]["timeout_seconds"]),
                min_interval_seconds=float(effective["wecom"].get("wecomapi_min_interval_seconds") or 0),
                daily_limit=int(effective["wecom"].get("wecomapi_daily_limit") or 200),
                failure_threshold=int(effective["wecom"].get("wecomapi_failure_threshold") or 3),
                cooldown_seconds=int(effective["wecom"].get("wecomapi_cooldown_seconds") or 300),
            ).send_text(protocol_room_id, content, mentioned_userids=mentioned_userids)
            self._log_result(group_id, content, result)
            return result
        result = {"success": False, "mode": mode, "status_code": None, "response": None, "error": "生产发送仅支持 wecomapi"}
        self._log_result(group_id, content, result)
        return result

    def resolve_mentioned_userids(
        self,
        group_id: str,
        mentioned_userids: list[str] | None,
        *,
        tenant_id: str | None = None,
    ) -> list[str]:
        requested = list(dict.fromkeys(str(value).strip() for value in (mentioned_userids or []) if str(value).strip()))
        if not requested:
            return []
        effective = self._effective_wecom_settings(tenant_id)
        if effective["wecom"]["send_mode"] != "wecomapi":
            return requested
        protocol_room_id = self._resolve_wecomapi_room_id(group_id)
        if not protocol_room_id:
            return []

        db = SessionLocal()
        try:
            resolved = self._contact_mappings(db, group_id, requested)
        finally:
            db.close()
        unresolved = [value for value in requested if value not in resolved]
        if unresolved:
            adapter = self._wecomapi_adapter(effective)
            room_result = adapter.get_room_details([protocol_room_id])
            room = next(iter(room_result.get("rooms") or []), None)
            raw_members = room.get("memberList") if isinstance(room, dict) else []
            member_ids = [
                str(member.get("userId") or "").strip()
                for member in raw_members
                if isinstance(member, dict) and str(member.get("userId") or "").strip()
            ]
            if member_ids:
                details = adapter.get_contact_details(member_ids)
                for contact in details.get("contacts") or []:
                    if not isinstance(contact, dict):
                        continue
                    protocol_user_id = str(contact.get("userId") or "").strip()
                    account_id = str(contact.get("acctid") or "").strip()
                    if protocol_user_id not in member_ids:
                        continue
                    if account_id:
                        resolved[account_id] = protocol_user_id
                    resolved[protocol_user_id] = protocol_user_id
        return list(dict.fromkeys(resolved[value] for value in requested if value in resolved))

    @staticmethod
    def _contact_mappings(db, group_id: str, identifiers: list[str]) -> dict[str, str]:
        rows = db.execute(
            select(Contact, ContactGroup)
            .join(ContactGroup, ContactGroup.contact_id == Contact.id)
            .where(
                ContactGroup.group_id == group_id,
                ContactGroup.membership_status != "left",
                Contact.is_active.is_(True),
                (Contact.archive_user_id.in_(identifiers)) | (Contact.wecomapi_user_id.in_(identifiers)),
            )
        ).all()
        result: dict[str, str] = {}
        for contact, _membership in rows:
            if not contact.wecomapi_user_id:
                continue
            if contact.archive_user_id:
                result[contact.archive_user_id] = contact.wecomapi_user_id
            result[contact.wecomapi_user_id] = contact.wecomapi_user_id
        return result

    @staticmethod
    def _wecomapi_adapter(effective: dict[str, Any]) -> WeComApiAdapter:
        return WeComApiAdapter(
            base_url=effective["wecom"].get("wecomapi_base_url"),
            api_path=str(effective["wecom"].get("wecomapi_api_path") or "/wecom/finder/api"),
            token=effective["wecom"].get("wecomapi_token"),
            token_header=str(effective["wecom"].get("wecomapi_token_header") or "WECOM-TOKEN"),
            guid=effective["wecom"].get("wecomapi_guid"),
            timeout_seconds=int(effective["wecom"]["timeout_seconds"]),
            min_interval_seconds=float(effective["wecom"].get("wecomapi_min_interval_seconds") or 0),
            daily_limit=int(effective["wecom"].get("wecomapi_daily_limit") or 200),
            failure_threshold=int(effective["wecom"].get("wecomapi_failure_threshold") or 3),
            cooldown_seconds=int(effective["wecom"].get("wecomapi_cooldown_seconds") or 300),
        )

    def _effective_wecom_settings(self, tenant_id: str | None) -> dict[str, Any]:
        if tenant_id is None:
            return {
                "source": "global",
                "wecom": {
                    "send_mode": self.mode,
                    "timeout_seconds": self.settings.wecom_timeout_seconds,
                    "max_retry": self.settings.wecom_max_retry,
                    "wecomapi_base_url": self.settings.wecomapi_base_url,
                    "wecomapi_api_path": self.settings.wecomapi_api_path,
                    "wecomapi_token": self.settings.wecomapi_token,
                    "wecomapi_token_header": self.settings.wecomapi_token_header,
                    "wecomapi_guid": self.settings.wecomapi_guid,
                    "wecomapi_min_interval_seconds": self.settings.wecomapi_min_interval_seconds,
                    "wecomapi_daily_limit": self.settings.wecomapi_daily_limit,
                    "wecomapi_failure_threshold": self.settings.wecomapi_failure_threshold,
                    "wecomapi_cooldown_seconds": self.settings.wecomapi_cooldown_seconds,
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
    def _log_result(group_id: str, content: str, result: dict[str, Any]) -> None:
        logger.info(
            "企业微信发送结果 mode=%s group_id=%s content_length=%s success=%s",
            result["mode"],
            group_id,
            len(content),
            result["success"],
        )
