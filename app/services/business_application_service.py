import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.group_message import GroupMessage
from app.services.document_sync_service import DocumentSyncService
from app.services.media_file_service import MediaFileService
from app.services.payment_service import PaymentService
from app.services.reminder_service import ReminderService
from app.services.tenant_settings_service import TenantSettingsService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import now_tz


class BusinessApplicationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def apply_event(self, event_id: int) -> None:
        event = self.db.get(LegalEvent, event_id)
        if not event:
            raise ValueError("业务事件不存在")
        if event.business_status == "applied":
            return
        if event.attribution_status != "confirmed" or not event.case_id:
            raise ValueError("案件归属未确认")
        if event.business_status != "approved":
            raise ValueError("业务事件尚未批准")
        legal_case = self.db.get(LegalCase, event.case_id)
        metadata = json.loads(event.metadata_json or "{}")
        media = self.db.get(MediaFile, metadata.get("media_file_id")) if metadata.get("media_file_id") else None
        if media:
            result = MediaFileService._load_result(media.review_result_json or media.ocr_result_json)
            MediaFileService(self.db)._apply_ocr_business(media, event, result, legal_case)
        else:
            self._apply_text_event(event, legal_case)
        event.business_status = "applied"
        event.applied_at = now_tz()
        self.db.flush()

    def _apply_text_event(self, event: LegalEvent, legal_case: LegalCase) -> None:
        message = self.db.get(GroupMessage, event.group_message_id) if event.group_message_id else None
        group_id = message.group_id if message else legal_case.group_id
        if WeComArchiveGroupService(self.db).feature_enabled(group_id, "document_sync"):
            DocumentSyncService(self.db).sync_archive_event(event)
        if event.event_type == "payment_screenshot" and event.amount is not None:
            _record, created = PaymentService(self.db).create(
                legal_case,
                amount=event.amount,
                source_event=event,
                status="approved",
                operator=event.approved_by or "system:outbox",
                payment_date=event.event_time.date() if event.event_time else None,
            )
            if created:
                DocumentSyncService(self.db).sync_paid_amount(legal_case)
        elif event.event_type == "payment_notice":
            effective = TenantSettingsService(self.db).get_effective_settings(legal_case.tenant_id)
            enabled = bool(effective["feature_flags"].get("enable_payment_tracking", True))
            if enabled and WeComArchiveGroupService(self.db).feature_enabled(group_id, "payment_tracking"):
                ReminderService(self.db).create_payment_tracking(
                    legal_case.id,
                    start_date=(event.event_time or now_tz()).date(),
                    days=7,
                    source_event_id=event.id,
                    payment_amount=event.amount,
                )
        elif event.event_type == "keyword":
            text = event.extracted_text or ""
            from app.services.case_service import CaseService

            if "强制执行" in text or "仲裁" in text:
                CaseService(self.db).mark_defaulted(legal_case)
            elif "逾期" in text:
                CaseService(self.db).mark_overdue(legal_case)
