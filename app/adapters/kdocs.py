import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class KDocsAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.mode = self.settings.kdocs_mode

    def update_case_status(self, case_no: str, status: str, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": {
                self.settings.kdocs_case_no_column: case_no,
                self.settings.kdocs_status_column: status,
            },
            "case_id": case_id,
        }
        return self._execute("update_case_status", payload)

    def update_paid_amount(self, case_no: str, paid_amount: Decimal, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": {
                self.settings.kdocs_case_no_column: case_no,
                self.settings.kdocs_paid_amount_column: str(paid_amount),
            },
            "case_id": case_id,
        }
        return self._execute("update_paid_amount", payload)

    def append_archive_row(self, data: dict[str, Any], case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": data,
            "case_id": case_id,
        }
        return self._execute("append_archive_row", payload)

    def sync_case_snapshot(self, case_data: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        case_no = case_data.get("case_no")
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": case_data,
            "case_id": case_data.get("id"),
        }
        return self._execute("sync_case_snapshot", payload)

    def upload_legal_document(
        self,
        local_path: str,
        target_filename: str,
        metadata: dict[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "folder_id": self.settings.kdocs_judgment_folder_id,
            "target_filename": target_filename,
            "local_path": local_path,
            "metadata": metadata,
            "conflict_strategy": "rename",
        }
        if self.mode == "mock":
            file_id = f"mock-kdocs-file-{Path(target_filename).stem}"
            return self._mock_result(
                "upload_legal_document",
                payload,
                response={
                    "file_id": file_id,
                    "final_filename": target_filename,
                    "url": f"kdocs://{self.settings.kdocs_judgment_folder_id}/{target_filename}",
                },
            )
        missing = self._missing_real_config()
        if missing:
            return self._missing_result("upload_legal_document", payload, missing)
        try:
            with open(local_path, "rb") as file_obj:
                response = httpx.post(
                    self._endpoint("files/upload"),
                    data={
                        "space_id": self.settings.kdocs_space_id,
                        "folder_id": self.settings.kdocs_judgment_folder_id,
                        "target_filename": target_filename,
                        "metadata": self._stringify(metadata),
                        "conflict_strategy": "rename",
                    },
                    files={"file": (target_filename, file_obj)},
                    headers=self._headers(),
                    timeout=self.settings.kdocs_timeout_seconds,
                )
            return self._response_result("upload_legal_document", payload, response)
        except Exception as exc:
            logger.exception("金山文档文件上传失败")
            return self._exception_result("upload_legal_document", payload, exc)

    def append_court_time_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_court_time_sheet_id,
            "sort_by": "开庭时间",
            "row": row,
        }
        return self._execute("append_court_time_row", payload)

    def append_enforcement_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": row,
        }
        return self._execute("append_enforcement_row", payload)

    def append_payment_registration_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_payment_sheet_id,
            "row": row,
        }
        return self._execute("append_payment_registration_row", payload)

    def _execute(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_result(operation, payload)
        missing = self._missing_real_config()
        if missing:
            return self._missing_result(operation, payload, missing)
        try:
            response = httpx.post(
                self._endpoint(operation),
                json=payload,
                headers=self._headers(),
                timeout=self.settings.kdocs_timeout_seconds,
            )
            return self._response_result(operation, payload, response)
        except Exception as exc:
            logger.exception("金山文档同步失败 operation=%s", operation)
            return self._exception_result(operation, payload, exc)

    def _missing_real_config(self) -> list[str]:
        missing = []
        if not self.settings.kdocs_base_url:
            missing.append("KDOCS_BASE_URL")
        if not self.settings.kdocs_access_token:
            missing.append("KDOCS_ACCESS_TOKEN")
        if not self.settings.kdocs_space_id:
            missing.append("KDOCS_SPACE_ID")
        return missing

    def _endpoint(self, operation: str) -> str:
        return f"{self.settings.kdocs_base_url.rstrip('/')}/kdocs/{operation}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.kdocs_access_token}"}

    def _mock_result(self, operation: str, payload: dict[str, Any], response: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "success": True,
            "mode": "mock",
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": response or {"mock": True, "operation": operation},
            "error": None,
        }

    def _missing_result(self, operation: str, payload: dict[str, Any], missing: list[str]) -> dict[str, Any]:
        return {
            "success": False,
            "mode": self.mode,
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": None,
            "error": f"金山文档真实同步配置缺失：{', '.join(missing)}",
        }

    def _exception_result(self, operation: str, payload: dict[str, Any], exc: Exception) -> dict[str, Any]:
        return {
            "success": False,
            "mode": self.mode,
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": None,
            "error": str(exc),
        }

    def _response_result(self, operation: str, payload: dict[str, Any], response: httpx.Response) -> dict[str, Any]:
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"text": response.text}
        business_success = response_payload.get("success") is not False if isinstance(response_payload, dict) else True
        success = response.status_code < 400 and business_success
        return {
            "success": success,
            "mode": "real",
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": response_payload,
            "error": None if success else self._response_error(response, response_payload),
        }

    @staticmethod
    def _response_error(response: httpx.Response, response_payload: Any) -> str:
        if response.status_code >= 400:
            return f"金山文档 API HTTP {response.status_code}"
        if isinstance(response_payload, dict):
            return str(response_payload.get("error") or response_payload.get("message") or "金山文档网关返回业务失败")
        return "金山文档网关返回业务失败"

    @staticmethod
    def _stringify(value: dict[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
