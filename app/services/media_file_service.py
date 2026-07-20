import json
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.wecom_media import WeComMediaAdapter
from app.core.config import get_settings
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.services.case_service import CaseService
from app.services.document_sync_service import DocumentSyncService
from app.services.ocr_service import OCRService
from app.services.reminder_service import ReminderService
from app.services.system_run_log_service import SystemRunLogService
from app.services.tenant_settings_service import TenantSettingsService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import now_tz
from app.utils.media_storage import MediaStorage

logger = logging.getLogger(__name__)


class MediaFileService:
    def __init__(
        self,
        db: Session,
        media_adapter: WeComMediaAdapter | None = None,
        storage: MediaStorage | None = None,
    ) -> None:
        self.db = db
        self.media_adapter = media_adapter or WeComMediaAdapter()
        self.storage = storage or MediaStorage()
        self.ocr_service = OCRService()
        self.case_service = CaseService(db)
        self.document_sync = DocumentSyncService(db)
        self.reminder_service = ReminderService(db)

    def create_media_from_message(
        self,
        group_message: GroupMessage,
        normalized_payload: dict[str, Any],
        case_id: int | None = None,
    ) -> MediaFile | None:
        media_type = self._media_type(group_message.msg_type)
        if media_type is None:
            return None

        raw_payload = normalized_payload.get("raw_payload_json") or {}
        file_info = self._file_info(media_type, raw_payload)
        media_file = MediaFile(
            group_message_id=group_message.id,
            case_id=case_id,
            tenant_id=group_message.tenant_id,
            group_id=group_message.group_id,
            msg_id=raw_payload.get("msgid"),
            seq=int(raw_payload["seq"]) if raw_payload.get("seq") is not None else None,
            media_type=media_type,
            original_filename=file_info.get("filename"),
            file_ext=file_info.get("file_ext"),
            mime_type=file_info.get("mime_type"),
            file_size=file_info.get("filesize"),
            md5sum=file_info.get("md5sum"),
            source="wecom_archive" if raw_payload else "mock",
            source_payload_json=json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
            download_status="pending",
            ocr_status="pending",
            metadata_json=json.dumps({"created_from": "message"}, ensure_ascii=False),
        )
        self.db.add(media_file)
        self.db.flush()
        return media_file

    def download_media_file(self, media_file_id: int) -> MediaFile:
        media_file = self._get_media_file(media_file_id)
        raw_payload = json.loads(media_file.source_payload_json or "{}")
        target_path = self.storage.build_local_path(
            msg_id=media_file.msg_id,
            seq=media_file.seq,
            original_filename=media_file.original_filename,
            media_type=media_file.media_type,
        )
        result = self.media_adapter.download_media(raw_payload, target_path)
        if result.get("success"):
            media_file.local_path = result["local_path"]
            media_file.file_size = result.get("file_size") or media_file.file_size
            media_file.public_url = self.storage.get_public_url(media_file.local_path)
            media_file.download_status = "downloaded"
            media_file.last_error = None
        else:
            media_file.download_status = "failed"
            media_file.last_error = result.get("error") or "媒体下载失败"
        self.db.flush()
        return media_file

    def process_ocr(self, media_file_id: int, trigger_type: str = "system", operator: str | None = None) -> dict[str, Any]:
        run_service = SystemRunLogService(self.db)
        run_log = run_service.start_run("ocr_process", trigger_type, summary={"media_file_id": media_file_id, **({"operator": operator} if operator else {})})
        media_file = self._get_media_file(media_file_id)
        if media_file.business_applied_at is not None:
            result = self._load_result(media_file.review_result_json or media_file.ocr_result_json)
            summary = self._ocr_summary(
                media_file,
                event_id=media_file.review_event_id,
                matched_case_id=media_file.case_id,
                event_type=result.get("event_type"),
                amount=result.get("amount"),
                result=result,
                message="该材料业务已执行，禁止普通重跑",
            )
            run_service.finish_success(run_log, summary=self._run_summary(summary), total_count=1, success_count=1, failed_count=0)
            return summary
        if media_file.review_status in {"approved", "corrected", "rejected"}:
            result = self._load_result(media_file.review_result_json or media_file.ocr_result_json)
            summary = self._ocr_summary(
                media_file,
                event_id=media_file.review_event_id,
                matched_case_id=media_file.case_id,
                event_type=result.get("event_type"),
                amount=result.get("amount"),
                result=result,
                message="该材料复核已结束，禁止普通重跑",
            )
            run_service.finish_success(run_log, summary=self._run_summary(summary), total_count=1, success_count=1, failed_count=0)
            return summary
        if media_file.ocr_status == "processed" and not get_settings().ocr_enable_reprocess:
            summary = self._ocr_summary(media_file, message="OCR 已处理，当前配置不允许重复处理")
            run_service.finish_success(run_log, summary=self._run_summary(summary), total_count=1, success_count=1, failed_count=0)
            return summary
        if media_file.download_status != "downloaded":
            media_file = self.download_media_file(media_file_id)
        if media_file.download_status != "downloaded" or not media_file.local_path:
            media_file.ocr_status = "skipped"
            self.db.flush()
            summary = self._ocr_summary(media_file, message="媒体文件未下载，跳过 OCR")
            run_service.finish_success(run_log, summary=self._run_summary(summary), total_count=1, success_count=1, failed_count=0)
            return summary

        try:
            result = self.ocr_service.extract_from_file(media_file.local_path, media_file.media_type, tenant_id=media_file.tenant_id)
            if not result.get("success"):
                media_file.extracted_text = ""
                media_file.metadata_json = json.dumps(result.get("metadata") or {}, ensure_ascii=False)
                media_file.ocr_status = "failed"
                media_file.last_error = result.get("error") or "OCR 处理失败"
                self.db.flush()
                summary = self._ocr_summary(media_file, error=media_file.last_error)
                run_service.finish_failed(run_log, media_file.last_error, summary=self._run_summary(summary))
                return summary

            extracted_text = result.get("raw_text") or result.get("extracted_text") or ""
            result["requires_review"] = self._result_requires_review(result)
            media_file.extracted_text = extracted_text
            media_file.ocr_result_json = self._dump_result(result)
            media_file.review_result_json = None
            media_file.metadata_json = json.dumps(
                {
                    **(result.get("metadata") or {}),
                    "provider": result.get("provider"),
                    "confidence": result.get("confidence"),
                },
                ensure_ascii=False,
                default=str,
            )
            media_file.ocr_status = "processed" if extracted_text else "skipped"
            media_file.last_error = None
            event = None
            created_reminders = 0
            cancelled_reminders = 0
            matched_case = self.case_service.find_case_for_message(
                result.get("case_no"),
                media_file.group_id,
                media_file.tenant_id,
            )
            if matched_case:
                media_file.case_id = matched_case.id
                media_file.tenant_id = matched_case.tenant_id or media_file.tenant_id
                self._backfill_group_message_events(media_file, matched_case.id, media_file.tenant_id)
            if extracted_text:
                event = self._upsert_ocr_event(media_file, result)
                media_file.review_event_id = event.id
                if result["requires_review"]:
                    media_file.review_status = "pending"
                else:
                    media_file.review_status = "not_required"
                    media_file.review_result_json = media_file.ocr_result_json
                    applied = self._apply_ocr_business(media_file, event, result, matched_case)
                    created_reminders = applied["created_reminders"]
                    cancelled_reminders = applied["cancelled_reminders"]
        except Exception as exc:
            logger.exception("媒体 OCR 处理失败 media_file_id=%s", media_file.id)
            media_file.ocr_status = "failed"
            media_file.last_error = str(exc)
            self.db.flush()
            summary = self._ocr_summary(media_file, error=str(exc))
            run_service.finish_failed(run_log, str(exc), summary=self._run_summary(summary))
            return summary
        self.db.flush()
        summary = self._ocr_summary(
            media_file,
            event_id=event.id if event else None,
            matched_case_id=media_file.case_id,
            event_type=result.get("event_type") or "unknown",
            amount=result.get("amount"),
            result=result,
            created_reminders=created_reminders,
        )
        summary["cancelled_reminders"] = cancelled_reminders
        run_service.finish_success(run_log, summary=self._run_summary(summary), total_count=1, success_count=1, failed_count=0)
        return summary

    def list_ocr_reviews(
        self,
        review_status: str | None = None,
        group_id: str | None = None,
        case_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[MediaFile]]:
        query = select(MediaFile).where(MediaFile.ocr_result_json.is_not(None))
        if review_status:
            query = query.where(MediaFile.review_status == review_status)
        if group_id:
            query = query.where(MediaFile.group_id == group_id)
        if case_id is not None:
            query = query.where(MediaFile.case_id == case_id)
        items = list(self.db.scalars(query.order_by(MediaFile.updated_at.desc(), MediaFile.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def decide_ocr_review(
        self,
        media_file_id: int,
        decision: str,
        operator: str,
        note: str | None = None,
        corrections: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        media_file = self._get_media_file(media_file_id)
        if media_file.review_status != "pending":
            if media_file.review_status in {"approved", "corrected", "rejected"}:
                return {
                    "media_file": media_file,
                    "already_decided": True,
                    "created_reminders": 0,
                    "cancelled_reminders": 0,
                }
            raise ValueError("该材料当前不需要人工复核")

        result = self._load_result(media_file.ocr_result_json)
        if decision == "rejected":
            media_file.review_status = "rejected"
            media_file.reviewed_by = operator
            media_file.reviewed_at = now_tz()
            media_file.review_note = note
            media_file.review_result_json = self._dump_result(result)
            self.db.flush()
            return {
                "media_file": media_file,
                "already_decided": False,
                "created_reminders": 0,
                "cancelled_reminders": 0,
            }

        if decision == "corrected":
            for key, value in (corrections or {}).items():
                result[key] = value
        result["requires_review"] = False
        result.setdefault("metadata", {})["review_decision"] = decision
        result["metadata"]["reviewed_by"] = operator
        result["metadata"]["reviewed_at"] = now_tz().isoformat()

        matched_case = self.case_service.find_case_for_message(
            result.get("case_no"),
            media_file.group_id,
            media_file.tenant_id,
        )
        if matched_case:
            media_file.case_id = matched_case.id
            media_file.tenant_id = matched_case.tenant_id or media_file.tenant_id
            self._backfill_group_message_events(media_file, matched_case.id, media_file.tenant_id)
        event = self._upsert_ocr_event(media_file, result)
        media_file.review_event_id = event.id
        media_file.review_status = decision
        media_file.reviewed_by = operator
        media_file.reviewed_at = now_tz()
        media_file.review_note = note
        media_file.review_result_json = self._dump_result(result)
        applied = self._apply_ocr_business(media_file, event, result, matched_case)
        self.db.flush()
        return {"media_file": media_file, "already_decided": False, **applied}

    def list_media_files(
        self,
        group_id: str | None = None,
        case_id: int | None = None,
        media_type: str | None = None,
        download_status: str | None = None,
        ocr_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[MediaFile]]:
        query = select(MediaFile)
        if group_id:
            query = query.where(MediaFile.group_id == group_id)
        if case_id is not None:
            query = query.where(MediaFile.case_id == case_id)
        if media_type:
            query = query.where(MediaFile.media_type == media_type)
        if download_status:
            query = query.where(MediaFile.download_status == download_status)
        if ocr_status:
            query = query.where(MediaFile.ocr_status == ocr_status)
        all_items = list(self.db.scalars(query.order_by(MediaFile.id.desc())).all())
        start = (page - 1) * page_size
        return len(all_items), all_items[start : start + page_size]

    def _get_media_file(self, media_file_id: int) -> MediaFile:
        media_file = self.db.get(MediaFile, media_file_id)
        if not media_file:
            raise ValueError("媒体文件不存在")
        return media_file

    @staticmethod
    def _media_type(msg_type: str) -> str | None:
        if msg_type in {"image", "pdf", "file"}:
            return msg_type
        return None

    @staticmethod
    def _file_info(media_type: str, raw_payload: dict[str, Any]) -> dict[str, Any]:
        if media_type == "image":
            image = raw_payload.get("image") or {}
            return {
                "filename": raw_payload.get("msgid") + ".jpg" if raw_payload.get("msgid") else None,
                "file_ext": ".jpg",
                "mime_type": "image/jpeg",
                "filesize": image.get("filesize"),
                "md5sum": image.get("md5sum"),
            }
        file_payload = raw_payload.get("file") or {}
        filename = file_payload.get("filename")
        file_ext = Path(filename or "").suffix or (".pdf" if media_type == "pdf" else None)
        return {
            "filename": filename,
            "file_ext": file_ext,
            "mime_type": "application/pdf" if media_type == "pdf" else None,
            "filesize": file_payload.get("filesize"),
            "md5sum": file_payload.get("md5sum"),
        }

    def _upsert_ocr_event(self, media_file: MediaFile, result: dict[str, Any]) -> LegalEvent:
        event = self.db.get(LegalEvent, media_file.review_event_id) if media_file.review_event_id else None
        if event is None:
            event = LegalEvent(group_message_id=media_file.group_message_id, event_type="unknown", metadata_json="{}")
            self.db.add(event)
        event.case_id = media_file.case_id
        event.tenant_id = media_file.tenant_id
        event.event_type = result.get("event_type") or "unknown"
        event.event_time = result.get("court_time") or result.get("event_time") or event.event_time or now_tz()
        event.amount = result.get("amount")
        event.extracted_text = result.get("raw_text") or result.get("extracted_text") or media_file.extracted_text
        event.metadata_json = json.dumps(
            {
                "source": "media_ocr",
                "media_file_id": media_file.id,
                "case_no": result.get("case_no"),
                "provider": result.get("provider"),
                "confidence": result.get("confidence"),
                "document_type": result.get("document_type"),
                "plaintiff": result.get("plaintiff"),
                "defendant": result.get("defendant"),
                "court_time": result.get("court_time"),
                "requires_review": bool(result.get("requires_review")),
                **(result.get("metadata") or {}),
            },
            ensure_ascii=False,
            default=str,
        )
        self.db.flush()
        return event

    def _apply_ocr_business(
        self,
        media_file: MediaFile,
        event: LegalEvent,
        result: dict[str, Any],
        matched_case: LegalCase | None,
    ) -> dict[str, int]:
        if media_file.business_applied_at is not None:
            return {"created_reminders": 0, "cancelled_reminders": 0}
        if WeComArchiveGroupService(self.db).feature_enabled(media_file.group_id, "document_sync"):
            self.document_sync.sync_archive_event(event, media_file=media_file)
            self._sync_kdocs_business(event, media_file, result, matched_case)
        created_reminders = 0
        cancelled_reminders = 0
        if matched_case and result.get("event_type") == "payment_notice" and self._payment_tracking_enabled(matched_case.tenant_id, media_file.group_id):
            created_reminders = self._create_ocr_payment_tracking_once(matched_case, media_file, event.id)
        if matched_case and result.get("event_type") == "payment_screenshot":
            if result.get("amount") is not None:
                self.case_service.update_paid_amount(matched_case, result["amount"])
            cancelled_reminders = self.reminder_service.cancel_pending_payment_tracking(
                matched_case.id,
                f"付款完成材料已确认（媒体 {media_file.id}）",
            )
        media_file.business_applied_at = now_tz()
        self.db.flush()
        return {"created_reminders": created_reminders, "cancelled_reminders": cancelled_reminders}

    @staticmethod
    def _result_requires_review(result: dict[str, Any]) -> bool:
        return bool(result.get("requires_review")) or (result.get("event_type") or "unknown") == "unknown"

    @staticmethod
    def _dump_result(result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, default=str)

    @staticmethod
    def _load_result(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        result = json.loads(raw)
        if result.get("amount") is not None:
            result["amount"] = Decimal(str(result["amount"]))
        if isinstance(result.get("amounts"), list):
            result["amounts"] = [Decimal(str(value)) for value in result["amounts"]]
        for key in ("court_time", "event_time"):
            value = result.get(key)
            if isinstance(value, str):
                try:
                    result[key] = datetime.fromisoformat(value)
                except ValueError:
                    pass
        return result

    def _backfill_group_message_events(self, media_file: MediaFile, case_id: int, tenant_id: str | None) -> None:
        if media_file.group_message_id is None:
            return
        group_message = self.db.get(GroupMessage, media_file.group_message_id)
        if group_message and tenant_id and group_message.tenant_id != tenant_id:
            group_message.tenant_id = tenant_id
        events = self.db.scalars(
            select(LegalEvent)
            .where(LegalEvent.group_message_id == media_file.group_message_id)
            .where(LegalEvent.case_id.is_(None))
        ).all()
        for event in events:
            event.case_id = case_id
            if tenant_id and event.tenant_id != tenant_id:
                event.tenant_id = tenant_id

    def _create_ocr_payment_tracking_once(self, legal_case: LegalCase, media_file: MediaFile, event_id: int) -> int:
        existing = self.db.scalar(
            select(Reminder)
            .where(Reminder.case_id == legal_case.id)
            .where(Reminder.reminder_type == "payment_tracking")
            .where(Reminder.content.contains(f"OCR:{media_file.group_message_id}:payment_notice"))
        )
        if existing:
            return 0
        source_event = self.db.get(LegalEvent, event_id)
        reminders = self.reminder_service.create_payment_tracking(
            legal_case.id,
            start_date=now_tz().date(),
            days=7,
            source_event_id=event_id,
            payment_amount=source_event.amount if source_event else None,
        )
        marker = f" OCR:{media_file.group_message_id}:payment_notice:event:{event_id}"
        for reminder in reminders:
            reminder.content = f"{reminder.content}{marker}"
        return len(reminders)

    def _sync_kdocs_business(
        self,
        event: LegalEvent,
        media_file: MediaFile,
        result: dict[str, Any],
        legal_case: LegalCase | None,
    ) -> None:
        event_type = result.get("event_type")
        if event_type == "judgment":
            upload_url = None
            target_filename = self._target_legal_document_filename(media_file, result)
            if media_file.local_path:
                upload_log = self.document_sync.sync_legal_document_upload(
                    media_file,
                    target_filename,
                    self._document_metadata(result, legal_case, media_file),
                )
                try:
                    upload_response = json.loads(upload_log.response_payload_json or "{}")
                    upload_url = upload_response.get("url") or upload_response.get("file_url")
                except Exception:
                    upload_url = None
            self.document_sync.sync_enforcement_progress(event, self._enforcement_row(result, legal_case, media_file, target_filename, upload_url))
            return

        if event_type == "court_notice":
            self.document_sync.sync_court_time(event, self._court_time_row(result, legal_case, media_file))
            return

        if event_type in {"payment_notice", "payment_screenshot"}:
            self.document_sync.sync_payment_registration(event, self._payment_registration_row(result, legal_case, media_file))

    def _document_metadata(self, result: dict[str, Any], legal_case: LegalCase | None, media_file: MediaFile) -> dict[str, Any]:
        return {
            "case_no": self._case_no(result, legal_case),
            "plaintiff": result.get("plaintiff"),
            "defendant": result.get("defendant"),
            "document_type": result.get("document_type"),
            "media_file_id": media_file.id,
            "msg_id": media_file.msg_id,
            "requires_review": bool(result.get("requires_review")),
        }

    def _enforcement_row(
        self,
        result: dict[str, Any],
        legal_case: LegalCase | None,
        media_file: MediaFile,
        target_filename: str,
        upload_url: str | None,
    ) -> dict[str, Any]:
        return {
            "案号": self._case_no(result, legal_case),
            "原告": result.get("plaintiff"),
            "被告": result.get("defendant") or (legal_case.debtor_name if legal_case else None),
            "文书类型": result.get("document_type"),
            "文件名": target_filename,
            "文件链接": upload_url or media_file.public_url or media_file.local_path,
            "识别摘要": (result.get("raw_text") or result.get("extracted_text") or "")[:500],
            "需人工复核": bool(result.get("requires_review")),
            "消息ID": media_file.msg_id,
        }

    def _court_time_row(self, result: dict[str, Any], legal_case: LegalCase | None, media_file: MediaFile) -> dict[str, Any]:
        court_time = result.get("court_time") or result.get("event_time")
        return {
            "案号": self._case_no(result, legal_case),
            "被告": legal_case.debtor_name if legal_case else result.get("defendant"),
            "开庭时间": court_time.isoformat() if hasattr(court_time, "isoformat") else court_time,
            "文件链接": media_file.public_url or media_file.local_path,
            "识别摘要": (result.get("raw_text") or result.get("extracted_text") or "")[:500],
            "需人工复核": bool(result.get("requires_review")),
            "消息ID": media_file.msg_id,
        }

    def _payment_registration_row(self, result: dict[str, Any], legal_case: LegalCase | None, media_file: MediaFile) -> dict[str, Any]:
        return {
            "案号": self._case_no(result, legal_case),
            "被告": legal_case.debtor_name if legal_case else result.get("defendant"),
            "缴费类型": "付款完成" if result.get("event_type") == "payment_screenshot" else "缴费通知",
            "金额": str(result.get("amount")) if result.get("amount") is not None else None,
            "文件链接": media_file.public_url or media_file.local_path,
            "识别摘要": (result.get("raw_text") or result.get("extracted_text") or "")[:500],
            "需人工复核": bool(result.get("requires_review")),
            "消息ID": media_file.msg_id,
        }

    def _target_legal_document_filename(self, media_file: MediaFile, result: dict[str, Any]) -> str:
        plaintiff = self._safe_kdocs_filename_part(result.get("plaintiff") or "未知原告")
        defendant = self._safe_kdocs_filename_part(result.get("defendant") or "未知被告")
        document_type = result.get("document_type") or "文书"
        ext = media_file.file_ext or Path(media_file.original_filename or "").suffix or ".pdf"
        return f"{plaintiff}-{defendant}{{{document_type}}}{ext}"

    @staticmethod
    def _safe_kdocs_filename_part(value: str) -> str:
        return re.sub(r"[\\/:*?\"<>|\r\n]+", "_", str(value)).strip(" ._") or "未知"

    @staticmethod
    def _case_no(result: dict[str, Any], legal_case: LegalCase | None) -> str | None:
        return result.get("case_no") or (legal_case.case_no if legal_case else None)

    def _payment_tracking_enabled(self, tenant_id: str | None, group_id: str) -> bool:
        effective = TenantSettingsService(self.db).get_effective_settings(tenant_id)
        return bool(effective["feature_flags"].get("enable_payment_tracking", True)) and WeComArchiveGroupService(self.db).feature_enabled(
            group_id,
            "payment_tracking",
        )

    @staticmethod
    def _ocr_summary(
        media_file: MediaFile,
        event_id: int | None = None,
        matched_case_id: int | None = None,
        event_type: str | None = None,
        amount: Any = None,
        result: dict[str, Any] | None = None,
        created_reminders: int = 0,
        error: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        court_time = (result or {}).get("court_time")
        return {
            "media_file": media_file,
            "media_file_id": media_file.id,
            "ocr_status": media_file.ocr_status,
            "event_id": event_id,
            "matched_case_id": matched_case_id,
            "event_type": event_type,
            "amount": str(amount) if amount is not None else None,
            "document_type": (result or {}).get("document_type"),
            "plaintiff": (result or {}).get("plaintiff"),
            "defendant": (result or {}).get("defendant"),
            "court_time": court_time.isoformat() if hasattr(court_time, "isoformat") else court_time,
            "requires_review": bool((result or {}).get("requires_review")),
            "extraction_confidence": (result or {}).get("extraction_confidence"),
            "review_reasons": (result or {}).get("review_reasons") or [],
            "parser": ((result or {}).get("metadata") or {}).get("parser"),
            "llm_status": ((result or {}).get("metadata") or {}).get("llm_status"),
            "created_reminders": created_reminders,
            "review_status": media_file.review_status,
            "business_applied": media_file.business_applied_at is not None,
            "error": error,
            "message": message,
        }

    @staticmethod
    def _run_summary(summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "media_file_id": summary.get("media_file_id"),
            "ocr_status": summary.get("ocr_status"),
            "event_type": summary.get("event_type"),
            "matched_case_id": summary.get("matched_case_id"),
            "event_id": summary.get("event_id"),
            "document_type": summary.get("document_type"),
            "plaintiff": summary.get("plaintiff"),
            "defendant": summary.get("defendant"),
            "court_time": summary.get("court_time"),
            "requires_review": summary.get("requires_review"),
            "extraction_confidence": summary.get("extraction_confidence"),
            "review_reasons": summary.get("review_reasons"),
            "parser": summary.get("parser"),
            "llm_status": summary.get("llm_status"),
            "created_reminders": summary.get("created_reminders"),
            "review_status": summary.get("review_status"),
            "business_applied": summary.get("business_applied"),
            "error": summary.get("error"),
        }
