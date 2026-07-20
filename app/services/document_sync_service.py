import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.kdocs import KDocsAdapter
from app.adapters.tencent_doc import TencentDocAdapter
from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.services.system_run_log_service import SystemRunLogService
from app.utils.datetime_utils import now_tz

logger = logging.getLogger(__name__)


class DocumentSyncService:
    def __init__(self, db: Session, adapter: Any | None = None) -> None:
        self.db = db
        self.settings = get_settings()
        self.adapter = adapter or KDocsAdapter()

    def sync_status(self, legal_case: LegalCase, status: str) -> DocumentSyncLog:
        payload = {
            "tenant_id": legal_case.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: legal_case.case_no},
            "fields": {
                self.settings.kdocs_case_no_column: legal_case.case_no,
                self.settings.kdocs_status_column: status,
            },
            "case_id": legal_case.id,
        }
        return self._execute_once(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            sync_type="status",
            operation="update_case_status",
            initial_payload=payload,
            callback=lambda: self.adapter.update_case_status(legal_case.case_no, status, legal_case.id, tenant_id=legal_case.tenant_id),
            external_sheet_name=self.settings.kdocs_case_sheet_id,
            external_row_key=legal_case.case_no,
            idempotency_key=f"kdocs:status:{legal_case.id}:{status}",
        )

    def sync_paid_amount(self, legal_case: LegalCase) -> DocumentSyncLog:
        payload = {
            "tenant_id": legal_case.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: legal_case.case_no},
            "fields": {
                self.settings.kdocs_case_no_column: legal_case.case_no,
                self.settings.kdocs_paid_amount_column: str(legal_case.paid_amount),
            },
            "case_id": legal_case.id,
        }
        return self._execute_once(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            sync_type="paid_amount",
            operation="update_paid_amount",
            initial_payload=payload,
            callback=lambda: self.adapter.update_paid_amount(
                legal_case.case_no,
                legal_case.paid_amount,
                legal_case.id,
                tenant_id=legal_case.tenant_id,
            ),
            external_sheet_name=self.settings.kdocs_case_sheet_id,
            external_row_key=legal_case.case_no,
            idempotency_key=f"kdocs:paid_amount:{legal_case.id}:{legal_case.paid_amount}",
        )

    def sync_archive_event(self, event: LegalEvent, media_file: MediaFile | None = None) -> DocumentSyncLog:
        legal_case = self.db.get(LegalCase, event.case_id) if event.case_id else None
        group_id = event.group_message.group_id if event.group_message else None
        payload = {
            "case_no": legal_case.case_no if legal_case else None,
            "group_id": group_id,
            "event_type": event.event_type,
            "amount": str(event.amount) if event.amount is not None else None,
            "event_time": event.event_time.isoformat() if event.event_time else None,
            "extracted_text": (event.extracted_text or "")[:500],
            "media_file_id": media_file.id if media_file else None,
            "local_path": media_file.local_path if media_file else None,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        tenant_id = event.tenant_id or (legal_case.tenant_id if legal_case else None)
        request_payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": payload,
            "case_id": event.case_id,
        }
        return self._execute_once(
            case_id=event.case_id,
            tenant_id=tenant_id,
            sync_type="archive",
            operation="append_archive_row",
            initial_payload=request_payload,
            callback=lambda: self.adapter.append_archive_row(payload, event.case_id, tenant_id=tenant_id),
            external_sheet_name=self.settings.kdocs_enforcement_sheet_id,
            external_row_key=legal_case.case_no if legal_case else None,
            idempotency_key=f"kdocs:archive:{event.id}",
        )

    def sync_case_snapshot(self, legal_case: LegalCase) -> DocumentSyncLog:
        case_data = {
            "id": legal_case.id,
            "case_no": legal_case.case_no,
            "debtor_name": legal_case.debtor_name,
            "group_id": legal_case.group_id,
            "due_date": legal_case.due_date.isoformat(),
            "status": legal_case.status,
            "total_amount": str(legal_case.total_amount),
            "paid_amount": str(legal_case.paid_amount),
        }
        payload = {
            "tenant_id": legal_case.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: legal_case.case_no},
            "fields": case_data,
            "case_id": legal_case.id,
        }
        return self._execute_once(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            sync_type="case_snapshot",
            operation="sync_case_snapshot",
            initial_payload=payload,
            callback=lambda: self.adapter.sync_case_snapshot(case_data, tenant_id=legal_case.tenant_id),
            external_sheet_name=self.settings.kdocs_case_sheet_id,
            external_row_key=legal_case.case_no,
            idempotency_key=f"kdocs:case_snapshot:{legal_case.id}:{legal_case.updated_at.isoformat()}",
        )

    def sync_legal_document_upload(
        self,
        media_file: MediaFile,
        target_filename: str,
        metadata: dict[str, Any],
    ) -> DocumentSyncLog:
        payload = {
            "tenant_id": media_file.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "folder_id": self.settings.kdocs_judgment_folder_id,
            "target_filename": target_filename,
            "local_path": media_file.local_path or "",
            "metadata": metadata,
            "conflict_strategy": "rename",
        }
        return self._execute_once(
            case_id=media_file.case_id,
            tenant_id=media_file.tenant_id,
            sync_type="legal_document_upload",
            operation="upload_legal_document",
            initial_payload=payload,
            callback=lambda: self.adapter.upload_legal_document(
                media_file.local_path or "",
                target_filename,
                metadata,
                tenant_id=media_file.tenant_id,
            ),
            external_sheet_name=self.settings.kdocs_judgment_folder_id,
            external_row_key=target_filename,
            idempotency_key=f"kdocs:legal_document_upload:{media_file.id}",
        )

    def sync_court_time(self, event: LegalEvent, row: dict[str, Any]) -> DocumentSyncLog:
        payload = {
            "tenant_id": event.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_court_time_sheet_id,
            "sort_by": "开庭时间",
            "row": row,
        }
        return self._execute_once(
            case_id=event.case_id,
            tenant_id=event.tenant_id,
            sync_type="court_time",
            operation="append_court_time_row",
            initial_payload=payload,
            callback=lambda: self.adapter.append_court_time_row(row, tenant_id=event.tenant_id),
            external_sheet_name=self.settings.kdocs_court_time_sheet_id,
            external_row_key=row.get("案号"),
            idempotency_key=f"kdocs:court_time:{event.id}",
        )

    def sync_enforcement_progress(self, event: LegalEvent, row: dict[str, Any]) -> DocumentSyncLog:
        payload = {
            "tenant_id": event.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": row,
        }
        return self._execute_once(
            case_id=event.case_id,
            tenant_id=event.tenant_id,
            sync_type="enforcement_progress",
            operation="append_enforcement_row",
            initial_payload=payload,
            callback=lambda: self.adapter.append_enforcement_row(row, tenant_id=event.tenant_id),
            external_sheet_name=self.settings.kdocs_enforcement_sheet_id,
            external_row_key=row.get("案号"),
            idempotency_key=f"kdocs:enforcement_progress:{event.id}",
        )

    def sync_payment_registration(self, event: LegalEvent, row: dict[str, Any]) -> DocumentSyncLog:
        payload = {
            "tenant_id": event.tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_payment_sheet_id,
            "row": row,
        }
        return self._execute_once(
            case_id=event.case_id,
            tenant_id=event.tenant_id,
            sync_type="payment_registration",
            operation="append_payment_registration_row",
            initial_payload=payload,
            callback=lambda: self.adapter.append_payment_registration_row(row, tenant_id=event.tenant_id),
            external_sheet_name=self.settings.kdocs_payment_sheet_id,
            external_row_key=row.get("案号"),
            idempotency_key=f"kdocs:payment_registration:{event.id}",
        )

    def retry_failed_sync(self, sync_log_id: int, operator: str | None = None) -> DocumentSyncLog:
        run_service = SystemRunLogService(self.db)
        run_log = run_service.start_run("document_sync_retry", "api", summary={"sync_log_id": sync_log_id, **({"operator": operator} if operator else {})})
        log = self.db.get(DocumentSyncLog, sync_log_id)
        if not log:
            run_service.finish_failed(run_log, "同步日志不存在", summary={"sync_log_id": sync_log_id, **({"operator": operator} if operator else {})})
            raise ValueError("同步日志不存在")
        if log.status != "failed":
            run_service.finish_success(
                run_log,
                summary={"sync_log_id": sync_log_id, "final_status": log.status, **({"operator": operator} if operator else {})},
                total_count=1,
                success_count=1,
                failed_count=0,
            )
            return log
        request_payload = json.loads(log.request_payload_json or "{}")
        operation = request_payload.get("operation")
        payload = request_payload.get("payload") or request_payload
        result = self._retry_operation(operation, payload, log)
        log.retry_count += 1
        log.last_attempt_at = now_tz()
        self._apply_result(log, result, operation=operation, fallback_payload=payload)
        self.db.flush()
        summary = {"sync_log_id": sync_log_id, "final_status": log.status, **({"operator": operator} if operator else {})}
        if log.status == "success":
            run_service.finish_success(run_log, summary=summary, total_count=1, success_count=1, failed_count=0)
        else:
            run_service.finish_partial(run_log, summary=summary, total_count=1, success_count=0, failed_count=1)
        return log

    def list_logs(
        self,
        status: str | None = None,
        sync_type: str | None = None,
        case_id: int | None = None,
        sync_target: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[DocumentSyncLog]]:
        query = select(DocumentSyncLog)
        if status:
            query = query.where(DocumentSyncLog.status == status)
        if sync_type:
            query = query.where(DocumentSyncLog.sync_type == sync_type)
        if case_id is not None:
            query = query.where(DocumentSyncLog.case_id == case_id)
        if sync_target:
            query = query.where(DocumentSyncLog.sync_target == sync_target)
        items = list(self.db.scalars(query.order_by(DocumentSyncLog.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def _retry_operation(self, operation: str | None, payload: dict[str, Any], log: DocumentSyncLog) -> dict[str, Any]:
        if operation == "update_case_status":
            row_match = payload.get("row_match") or {}
            fields = payload.get("fields") or {}
            tenant_id = log.tenant_id
            return self.adapter.update_case_status(
                row_match.get(self.settings.kdocs_case_no_column) or row_match.get(self.settings.tencent_doc_case_no_column) or log.external_row_key or "",
                fields.get(self.settings.kdocs_status_column) or fields.get(self.settings.tencent_doc_status_column) or "",
                log.case_id,
                tenant_id=tenant_id,
            )
        if operation == "update_paid_amount":
            row_match = payload.get("row_match") or {}
            fields = payload.get("fields") or {}
            return self.adapter.update_paid_amount(
                row_match.get(self.settings.kdocs_case_no_column) or row_match.get(self.settings.tencent_doc_case_no_column) or log.external_row_key or "",
                Decimal(str(fields.get(self.settings.kdocs_paid_amount_column) or fields.get(self.settings.tencent_doc_paid_amount_column) or "0")),
                log.case_id,
                tenant_id=log.tenant_id,
            )
        if operation == "append_archive_row":
            return self.adapter.append_archive_row(payload.get("row") or payload, log.case_id, tenant_id=log.tenant_id)
        if operation == "sync_case_snapshot":
            return self.adapter.sync_case_snapshot(payload.get("fields") or payload, tenant_id=log.tenant_id)
        if operation == "upload_legal_document":
            return self.adapter.upload_legal_document(
                payload.get("local_path") or "",
                payload.get("target_filename") or "",
                payload.get("metadata") or {},
                tenant_id=log.tenant_id,
            )
        if operation == "append_court_time_row":
            return self.adapter.append_court_time_row(payload.get("row") or payload, tenant_id=log.tenant_id)
        if operation == "append_enforcement_row":
            return self.adapter.append_enforcement_row(payload.get("row") or payload, tenant_id=log.tenant_id)
        if operation == "append_payment_registration_row":
            return self.adapter.append_payment_registration_row(payload.get("row") or payload, tenant_id=log.tenant_id)
        return {
            "success": False,
            "mode": self.settings.kdocs_mode,
            "sync_target": "kdocs",
            "operation": operation or "unknown",
            "request_payload": payload,
            "response": None,
            "error": "无法识别的同步操作",
        }

    def _execute_once(
        self,
        *,
        case_id: int | None,
        tenant_id: str | None,
        sync_type: str,
        operation: str,
        initial_payload: dict[str, Any],
        callback,
        external_sheet_name: str | None,
        external_row_key: str | None,
        idempotency_key: str,
    ) -> DocumentSyncLog:
        existing = self.db.scalar(
            select(DocumentSyncLog).where(DocumentSyncLog.idempotency_key == idempotency_key)
        )
        if existing:
            return existing

        log = DocumentSyncLog(
            case_id=case_id,
            tenant_id=tenant_id,
            sync_type=sync_type,
            sync_target="kdocs",
            external_doc_id=initial_payload.get("sheet_id") or initial_payload.get("folder_id") or self.settings.kdocs_space_id,
            external_sheet_name=external_sheet_name,
            external_row_key=external_row_key,
            idempotency_key=idempotency_key,
            request_payload_json=json.dumps(
                {"operation": operation, "payload": initial_payload},
                ensure_ascii=False,
                default=str,
            ),
            response_payload_json="{}",
            status="processing",
            error_message=None,
            retry_count=0,
            last_attempt_at=now_tz(),
        )
        try:
            with self.db.begin_nested():
                self.db.add(log)
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(
                select(DocumentSyncLog).where(DocumentSyncLog.idempotency_key == idempotency_key)
            )
            if existing:
                return existing
            raise

        result = self._safe_call(callback, operation)
        self._apply_result(log, result, operation=operation, fallback_payload=initial_payload)
        self.db.flush()
        return log

    def _apply_result(
        self,
        log: DocumentSyncLog,
        result: dict[str, Any],
        *,
        operation: str | None,
        fallback_payload: dict[str, Any],
    ) -> None:
        request_payload = result.get("request_payload") or fallback_payload
        response = result.get("response")
        log.sync_target = result.get("sync_target") or log.sync_target or "kdocs"
        log.external_doc_id = request_payload.get("sheet_id") or request_payload.get("folder_id") or log.external_doc_id
        log.external_sheet_name = (
            request_payload.get("sheet_name")
            or request_payload.get("sheet_id")
            or request_payload.get("folder_id")
            or log.external_sheet_name
        )
        final_filename = self._final_filename(response)
        if final_filename:
            log.external_row_key = final_filename
        log.request_payload_json = json.dumps(
            {"operation": result.get("operation") or operation, "payload": request_payload},
            ensure_ascii=False,
            default=str,
        )
        log.response_payload_json = json.dumps(response, ensure_ascii=False, default=str)
        log.status = "success" if result.get("success") else "failed"
        log.error_message = result.get("error")
        log.last_attempt_at = now_tz()

    @staticmethod
    def _final_filename(response: Any) -> str | None:
        if not isinstance(response, dict):
            return None
        containers = [response]
        if isinstance(response.get("data"), dict):
            containers.append(response["data"])
        for payload in containers:
            value = payload.get("final_filename") or payload.get("filename") or payload.get("name")
            if value:
                return str(value)
        return None

    @staticmethod
    def _safe_call(callback, operation: str) -> dict[str, Any]:
        try:
            return callback()
        except Exception as exc:
            logger.exception("文档同步调用异常 operation=%s", operation)
            return {
                "success": False,
                "mode": get_settings().kdocs_mode,
                "sync_target": "kdocs",
                "operation": operation,
                "request_payload": {},
                "response": None,
                "error": str(exc),
            }
