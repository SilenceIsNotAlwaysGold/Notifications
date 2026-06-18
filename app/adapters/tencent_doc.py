import logging
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.tenant_settings_service import TenantSettingsService

logger = logging.getLogger(__name__)


class TencentDocAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.mode = self.settings.tencent_doc_mode

    def update_case_status(self, case_no: str, status: str, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        effective = self._effective_doc_settings(tenant_id)
        doc = effective["tencent_doc"]
        payload = {
            "tenant_id": tenant_id,
            "tenant_settings_source": effective["source"],
            "sheet_id": doc["sheet_id"],
            "sheet_name": doc["case_sheet_name"],
            "row_match": {doc["case_no_column"]: case_no},
            "fields": {
                doc["case_no_column"]: case_no,
                doc["status_column"]: status,
            },
            "case_id": case_id,
        }
        return self._execute("update_case_status", payload, effective)

    def update_paid_amount(self, case_no: str, paid_amount: Decimal, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        effective = self._effective_doc_settings(tenant_id)
        doc = effective["tencent_doc"]
        payload = {
            "tenant_id": tenant_id,
            "tenant_settings_source": effective["source"],
            "sheet_id": doc["sheet_id"],
            "sheet_name": doc["case_sheet_name"],
            "row_match": {doc["case_no_column"]: case_no},
            "fields": {
                doc["case_no_column"]: case_no,
                doc["paid_amount_column"]: str(paid_amount),
            },
            "case_id": case_id,
        }
        return self._execute("update_paid_amount", payload, effective)

    def append_archive_row(self, data: dict[str, Any], case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        effective = self._effective_doc_settings(tenant_id)
        doc = effective["tencent_doc"]
        payload = {
            "tenant_id": tenant_id,
            "tenant_settings_source": effective["source"],
            "sheet_id": doc["sheet_id"],
            "sheet_name": doc["archive_sheet_name"],
            "row": data,
            "case_id": case_id,
        }
        return self._execute("append_archive_row", payload, effective)

    def sync_case_snapshot(self, case_data: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        effective = self._effective_doc_settings(tenant_id)
        doc = effective["tencent_doc"]
        case_no = case_data.get("case_no")
        payload = {
            "tenant_id": tenant_id,
            "tenant_settings_source": effective["source"],
            "sheet_id": doc["sheet_id"],
            "sheet_name": doc["case_sheet_name"],
            "row_match": {doc["case_no_column"]: case_no},
            "fields": case_data,
            "case_id": case_data.get("id"),
        }
        return self._execute("sync_case_snapshot", payload, effective)

    def _execute(self, operation: str, payload: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
        doc = effective["tencent_doc"]
        mode = doc["mode"]
        if not effective["feature_flags"].get("enable_tencent_doc_sync", True):
            return {
                "success": False,
                "skipped": True,
                "mode": mode,
                "operation": operation,
                "request_payload": payload,
                "response": {"skipped": True, "reason": "tenant_feature_disabled"},
                "error": "租户已关闭腾讯文档同步",
            }
        if mode == "mock":
            return {
                "success": True,
                "mode": "mock",
                "operation": operation,
                "request_payload": payload,
                "response": {"mock": True, "operation": operation},
                "error": None,
            }
        missing = self._missing_effective_real_config(doc)
        if missing:
            return {
                "success": False,
                "mode": mode,
                "operation": operation,
                "request_payload": payload,
                "response": None,
                "error": f"腾讯文档真实同步配置缺失：{', '.join(missing)}",
            }
        try:
            endpoint = f"{doc['base_url'].rstrip('/')}/sheets/{doc['sheet_id']}/{operation}"
            response = httpx.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {doc['access_token']}"},
                timeout=doc["timeout_seconds"],
            )
            try:
                response_payload = response.json()
            except ValueError:
                response_payload = {"text": response.text}
            success = response.status_code < 400
            return {
                "success": success,
                "mode": "real",
                "operation": operation,
                "request_payload": payload,
                "response": response_payload,
                "error": None if success else f"腾讯文档 API HTTP {response.status_code}",
            }
        except Exception as exc:
            logger.exception("腾讯文档真实同步失败 operation=%s", operation)
            return {
                "success": False,
                "mode": "real",
                "operation": operation,
                "request_payload": payload,
                "response": None,
                "error": str(exc),
            }

    def _missing_effective_real_config(self, doc: dict[str, Any]) -> list[str]:
        missing = []
        if not doc.get("base_url"):
            missing.append("TENCENT_DOC_BASE_URL")
        if not doc.get("access_token"):
            missing.append("TENCENT_DOC_ACCESS_TOKEN")
        if not doc.get("sheet_id"):
            missing.append("TENCENT_DOC_SHEET_ID")
        return missing

    def _effective_doc_settings(self, tenant_id: str | None) -> dict[str, Any]:
        if tenant_id is None:
            return {
                "source": "global",
                "tencent_doc": {
                    "mode": self.mode,
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
                "feature_flags": {"enable_tencent_doc_sync": True},
            }
        db = SessionLocal()
        try:
            return TenantSettingsService(db).get_effective_settings(tenant_id)
        finally:
            db.close()
