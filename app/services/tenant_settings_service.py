import base64
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tenant_setting import TenantSetting
from app.schemas.legal import TenantSettingsIn
from app.utils.datetime_utils import now_tz


DEFAULT_KEYWORD_CONFIG: dict[str, list[str]] = {
    "payment_notice": ["需要缴费", "缴费通知", "缴费金额", "诉讼费", "公告费", "开庭费", "缴纳"],
    "payment_done": ["已付款", "已支付", "支付成功", "转账成功", "已缴费", "付款截图"],
    "court_notice": ["传票", "开庭", "现场开庭"],
    "judgment": ["判决书", "民事判决书", "调解书", "民事调解书", "裁定书", "民事裁定书"],
    "default": ["强制执行", "仲裁", "逾期"],
}

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "enable_wecom_send": True,
    "enable_tencent_doc_sync": True,
    "enable_ocr": True,
    "enable_case_lifecycle_scan": True,
    "enable_payment_tracking": True,
}


class TenantSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def get_effective_settings(self, tenant_id: str | None, masked: bool = False) -> dict[str, Any]:
        global_values = self._global_settings(tenant_id)
        if not tenant_id or not self.settings.tenant_settings_enabled:
            if masked:
                return self._mask_effective(global_values)
            return global_values

        tenant_setting = self.get_raw_settings(tenant_id)
        if not tenant_setting:
            if masked:
                return self._mask_effective(global_values)
            return global_values

        result = self._merge_settings(global_values, tenant_setting)
        if masked:
            return self._mask_effective(result)
        return result

    def get_settings_for_api(self, tenant_id: str) -> dict[str, Any]:
        tenant_setting = self.get_raw_settings(tenant_id)
        if not tenant_setting:
            return self.get_effective_settings(tenant_id, masked=True)
        return {
            "tenant_id": tenant_id,
            "source": "tenant",
            "wecom_send_mode": tenant_setting.wecom_send_mode,
            "has_wecom_webhook_url": bool(tenant_setting.wecom_webhook_url_encrypted),
            "wecom_webhook_url": self.settings.secret_value_mask if tenant_setting.wecom_webhook_url_encrypted else None,
            "wecom_timeout_seconds": tenant_setting.wecom_timeout_seconds,
            "wecom_max_retry": tenant_setting.wecom_max_retry,
            "tencent_doc_mode": tenant_setting.tencent_doc_mode,
            "tencent_doc_base_url": tenant_setting.tencent_doc_base_url,
            "has_tencent_doc_access_token": bool(tenant_setting.tencent_doc_access_token_encrypted),
            "tencent_doc_access_token": self.settings.secret_value_mask if tenant_setting.tencent_doc_access_token_encrypted else None,
            "tencent_doc_sheet_id": tenant_setting.tencent_doc_sheet_id,
            "tencent_doc_case_sheet_name": tenant_setting.tencent_doc_case_sheet_name,
            "tencent_doc_archive_sheet_name": tenant_setting.tencent_doc_archive_sheet_name,
            "tencent_doc_case_no_column": tenant_setting.tencent_doc_case_no_column,
            "tencent_doc_status_column": tenant_setting.tencent_doc_status_column,
            "tencent_doc_paid_amount_column": tenant_setting.tencent_doc_paid_amount_column,
            "tencent_doc_timeout_seconds": tenant_setting.tencent_doc_timeout_seconds,
            "ocr_provider": tenant_setting.ocr_provider,
            "ocr_enable_reprocess": tenant_setting.ocr_enable_reprocess,
            "ocr_max_text_length": tenant_setting.ocr_max_text_length,
            "repayment_reminder_days_before": tenant_setting.repayment_reminder_days_before,
            "default_upgrade_days_after_overdue": tenant_setting.default_upgrade_days_after_overdue,
            "case_status_scan_enabled": tenant_setting.case_status_scan_enabled,
            "keyword_config": self._load_json(tenant_setting.keyword_config_json, {}),
            "feature_flags": self._load_json(tenant_setting.feature_flags_json, {}),
        }

    def create_or_update_settings(self, tenant_id: str, payload: TenantSettingsIn, operator: str | None = None) -> TenantSetting:
        tenant_setting = self.get_raw_settings(tenant_id)
        if not tenant_setting:
            tenant_setting = TenantSetting(tenant_id=tenant_id)
            self.db.add(tenant_setting)
        data = payload.model_dump(exclude_unset=True)
        for field in self._plain_fields():
            if field in data:
                setattr(tenant_setting, field, data[field])
        if "wecom_webhook_url" in data:
            tenant_setting.wecom_webhook_url_encrypted = self._encrypt_secret(data["wecom_webhook_url"])
        if "tencent_doc_access_token" in data:
            tenant_setting.tencent_doc_access_token_encrypted = self._encrypt_secret(data["tencent_doc_access_token"])
        if "keyword_config" in data:
            tenant_setting.keyword_config_json = json.dumps(data["keyword_config"] or {}, ensure_ascii=False)
        if "feature_flags" in data:
            tenant_setting.feature_flags_json = json.dumps(data["feature_flags"] or {}, ensure_ascii=False)
        tenant_setting.updated_at = now_tz()
        self.db.flush()
        return tenant_setting

    def delete_settings(self, tenant_id: str) -> bool:
        tenant_setting = self.get_raw_settings(tenant_id)
        if not tenant_setting:
            return False
        self.db.delete(tenant_setting)
        self.db.flush()
        return True

    def get_raw_settings(self, tenant_id: str) -> TenantSetting | None:
        return self.db.scalar(select(TenantSetting).where(TenantSetting.tenant_id == tenant_id))

    def _global_settings(self, tenant_id: str | None) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "source": "global",
            "wecom": {
                "send_mode": self.settings.wecom_send_mode,
                "webhook_url": self.settings.wecom_webhook_url,
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
            "tencent_doc": {
                "mode": self.settings.tencent_doc_mode,
                "base_url": self.settings.tencent_doc_base_url,
                "access_token": self.settings.tencent_doc_access_token,
                "sheet_id": self.settings.tencent_doc_sheet_id,
                "case_sheet_name": self.settings.tencent_doc_case_sheet_name,
                "archive_sheet_name": self.settings.tencent_doc_archive_sheet_name,
                "case_no_column": self.settings.tencent_doc_case_no_column,
                "status_column": self.settings.tencent_doc_status_column,
                "paid_amount_column": self.settings.tencent_doc_paid_amount_column,
                "timeout_seconds": self.settings.tencent_doc_timeout_seconds,
            },
            "ocr": {
                "provider": self.settings.ocr_provider,
                "enable_reprocess": self.settings.ocr_enable_reprocess,
                "max_text_length": self.settings.ocr_max_text_length,
            },
            "reminder": {
                "repayment_reminder_days_before": self.settings.repayment_reminder_days_before,
                "default_upgrade_days_after_overdue": self.settings.default_upgrade_days_after_overdue,
                "case_status_scan_enabled": self.settings.case_status_scan_enabled,
            },
            "feature_flags": dict(DEFAULT_FEATURE_FLAGS),
            "keyword_config": dict(DEFAULT_KEYWORD_CONFIG),
        }

    def _merge_settings(self, global_values: dict[str, Any], tenant_setting: TenantSetting) -> dict[str, Any]:
        result = json.loads(json.dumps(global_values, ensure_ascii=False, default=str))
        result["source"] = "tenant" if self._has_any_override(tenant_setting) else "global"
        self._set_if_not_none(result["wecom"], "send_mode", tenant_setting.wecom_send_mode)
        self._set_if_not_none(result["wecom"], "webhook_url", self._decrypt_secret(tenant_setting.wecom_webhook_url_encrypted))
        self._set_if_not_none(result["wecom"], "timeout_seconds", tenant_setting.wecom_timeout_seconds)
        self._set_if_not_none(result["wecom"], "max_retry", tenant_setting.wecom_max_retry)

        self._set_if_not_none(result["tencent_doc"], "mode", tenant_setting.tencent_doc_mode)
        self._set_if_not_none(result["tencent_doc"], "base_url", tenant_setting.tencent_doc_base_url)
        self._set_if_not_none(result["tencent_doc"], "access_token", self._decrypt_secret(tenant_setting.tencent_doc_access_token_encrypted))
        self._set_if_not_none(result["tencent_doc"], "sheet_id", tenant_setting.tencent_doc_sheet_id)
        self._set_if_not_none(result["tencent_doc"], "case_sheet_name", tenant_setting.tencent_doc_case_sheet_name)
        self._set_if_not_none(result["tencent_doc"], "archive_sheet_name", tenant_setting.tencent_doc_archive_sheet_name)
        self._set_if_not_none(result["tencent_doc"], "case_no_column", tenant_setting.tencent_doc_case_no_column)
        self._set_if_not_none(result["tencent_doc"], "status_column", tenant_setting.tencent_doc_status_column)
        self._set_if_not_none(result["tencent_doc"], "paid_amount_column", tenant_setting.tencent_doc_paid_amount_column)
        self._set_if_not_none(result["tencent_doc"], "timeout_seconds", tenant_setting.tencent_doc_timeout_seconds)

        self._set_if_not_none(result["ocr"], "provider", tenant_setting.ocr_provider)
        self._set_if_not_none(result["ocr"], "enable_reprocess", tenant_setting.ocr_enable_reprocess)
        self._set_if_not_none(result["ocr"], "max_text_length", tenant_setting.ocr_max_text_length)

        self._set_if_not_none(result["reminder"], "repayment_reminder_days_before", tenant_setting.repayment_reminder_days_before)
        self._set_if_not_none(result["reminder"], "default_upgrade_days_after_overdue", tenant_setting.default_upgrade_days_after_overdue)
        self._set_if_not_none(result["reminder"], "case_status_scan_enabled", tenant_setting.case_status_scan_enabled)

        result["feature_flags"] = {**DEFAULT_FEATURE_FLAGS, **self._load_json(tenant_setting.feature_flags_json, {})}
        result["keyword_config"] = {**DEFAULT_KEYWORD_CONFIG, **self._load_json(tenant_setting.keyword_config_json, {})}
        return result

    def _mask_effective(self, effective: dict[str, Any]) -> dict[str, Any]:
        masked = json.loads(json.dumps(effective, ensure_ascii=False, default=str))
        webhook_url = masked["wecom"].get("webhook_url")
        wecomapi_token = masked["wecom"].get("wecomapi_token")
        wecom_bot_token = masked["wecom"].get("wecom_bot_sidecar_token")
        access_token = masked["tencent_doc"].get("access_token")
        masked["wecom"]["has_webhook_url"] = bool(webhook_url)
        masked["wecom"]["webhook_url"] = self.settings.secret_value_mask if webhook_url else None
        masked["wecom"]["has_wecomapi_token"] = bool(wecomapi_token)
        masked["wecom"]["wecomapi_token"] = self.settings.secret_value_mask if wecomapi_token else None
        masked["wecom"]["has_wecom_bot_sidecar_token"] = bool(wecom_bot_token)
        masked["wecom"]["wecom_bot_sidecar_token"] = self.settings.secret_value_mask if wecom_bot_token else None
        masked["tencent_doc"]["has_access_token"] = bool(access_token)
        masked["tencent_doc"]["access_token"] = self.settings.secret_value_mask if access_token else None
        return masked

    @staticmethod
    def _set_if_not_none(target: dict[str, Any], key: str, value: Any) -> None:
        if value is not None:
            target[key] = value

    @staticmethod
    def _load_json(raw: str | None, default: dict[str, Any]) -> dict[str, Any]:
        if not raw:
            return dict(default)
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else dict(default)
        except Exception:
            return dict(default)

    @staticmethod
    def _encrypt_secret(value: str | None) -> str | None:
        if value is None:
            return None
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")

    @staticmethod
    def _decrypt_secret(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8")
        except Exception:
            return None

    @staticmethod
    def _plain_fields() -> list[str]:
        return [
            "wecom_send_mode",
            "wecom_timeout_seconds",
            "wecom_max_retry",
            "tencent_doc_mode",
            "tencent_doc_base_url",
            "tencent_doc_sheet_id",
            "tencent_doc_case_sheet_name",
            "tencent_doc_archive_sheet_name",
            "tencent_doc_case_no_column",
            "tencent_doc_status_column",
            "tencent_doc_paid_amount_column",
            "tencent_doc_timeout_seconds",
            "ocr_provider",
            "ocr_enable_reprocess",
            "ocr_max_text_length",
            "repayment_reminder_days_before",
            "default_upgrade_days_after_overdue",
            "case_status_scan_enabled",
        ]

    @staticmethod
    def _has_any_override(tenant_setting: TenantSetting) -> bool:
        values = [
            tenant_setting.wecom_send_mode,
            tenant_setting.wecom_webhook_url_encrypted,
            tenant_setting.wecom_timeout_seconds,
            tenant_setting.wecom_max_retry,
            tenant_setting.tencent_doc_mode,
            tenant_setting.tencent_doc_base_url,
            tenant_setting.tencent_doc_access_token_encrypted,
            tenant_setting.tencent_doc_sheet_id,
            tenant_setting.tencent_doc_case_sheet_name,
            tenant_setting.tencent_doc_archive_sheet_name,
            tenant_setting.tencent_doc_case_no_column,
            tenant_setting.tencent_doc_status_column,
            tenant_setting.tencent_doc_paid_amount_column,
            tenant_setting.tencent_doc_timeout_seconds,
            tenant_setting.ocr_provider,
            tenant_setting.ocr_enable_reprocess,
            tenant_setting.ocr_max_text_length,
            tenant_setting.repayment_reminder_days_before,
            tenant_setting.default_upgrade_days_after_overdue,
            tenant_setting.case_status_scan_enabled,
            tenant_setting.keyword_config_json,
            tenant_setting.feature_flags_json,
        ]
        return any(value is not None for value in values)
