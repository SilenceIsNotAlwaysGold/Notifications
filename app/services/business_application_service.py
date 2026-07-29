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
from app.services.payment_tracking_service import PaymentTrackingService
from app.services.reminder_service import ReminderService
from app.services.tenant_settings_service import TenantSettingsService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import ensure_aware, now_tz


class BusinessApplicationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def apply_event(self, event_id: int) -> None:
        event = self.db.get(LegalEvent, event_id)
        if not event:
            raise ValueError("业务事件不存在")
        if event.business_status == "applied":
            return
        case_independent_media = event.event_type in {
            "court_notice",
            "judgment",
            "repayment_agreement",
            "payment_screenshot",
        } and event.attribution_status == "not_required"
        if not case_independent_media and (event.attribution_status != "confirmed" or not event.case_id):
            raise ValueError("案件归属未确认")
        if event.business_status != "approved":
            raise ValueError("业务事件尚未批准")
        legal_case = self.db.get(LegalCase, event.case_id) if event.case_id else None
        metadata = json.loads(event.metadata_json or "{}")
        media = self.db.get(MediaFile, metadata.get("media_file_id")) if metadata.get("media_file_id") else None
        if media:
            result = MediaFileService._load_result(media.review_result_json or media.ocr_result_json)
            MediaFileService(self.db)._apply_ocr_business(media, event, result, legal_case)
        else:
            if not legal_case:
                raise ValueError("开庭传票缺少原始截图")
            self._apply_text_event(event, legal_case)
        event.business_status = "applied"
        event.applied_at = now_tz()
        self.db.flush()

    def _apply_text_event(self, event: LegalEvent, legal_case: LegalCase) -> None:
        metadata = json.loads(event.metadata_json or "{}")
        message = self.db.get(GroupMessage, event.group_message_id) if event.group_message_id else None
        group_id = message.group_id if message else legal_case.group_id
        if WeComArchiveGroupService(self.db).feature_enabled(group_id, "document_sync"):
            DocumentSyncService(self.db).sync_archive_event(event)
        if event.event_type == "payment_screenshot":
            installment_sequence = metadata.get("structured_fields", {}).get("installment_sequence")
            is_repayment = bool(metadata.get("repayment_annotation"))
            payment_service = PaymentService(self.db)
            matched_notice = None if is_repayment else payment_service.single_open_notice(legal_case.id)
            amount = event.amount or (matched_notice[1] if matched_notice else None)
            if amount is None:
                raise ValueError("付款确认缺少金额，且无法唯一匹配待缴费通知，请人工补充或关联")
            _record, created = payment_service.create(
                legal_case,
                amount=amount,
                record_type="repayment" if is_repayment else "fee_payment",
                source_event=event,
                applies_to_event_id=matched_notice[0].id if matched_notice else None,
                status="approved",
                operator=event.approved_by or "system:outbox",
                payment_date=event.event_time.date() if event.event_time else None,
                payer_name=metadata.get("repayment_annotation", {}).get("defendant"),
                note=f"第 {installment_sequence} 期还款" if installment_sequence else None,
            )
            if created and is_repayment:
                DocumentSyncService(self.db).sync_paid_amount(legal_case)
        elif event.event_type == "payment_notice":
            effective = TenantSettingsService(self.db).get_effective_settings(legal_case.tenant_id)
            enabled = bool(effective["feature_flags"].get("enable_payment_tracking", True))
            if enabled and WeComArchiveGroupService(self.db).feature_enabled(group_id, "payment_tracking"):
                start_date = (event.event_time or now_tz()).date()
                structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
                reminder_group_id, reminder_target = PaymentTrackingService(self.db).reminder_destination(event, legal_case)
                ReminderService(self.db).create_payment_tracking(
                    legal_case.id,
                    start_date=start_date,
                    days=7,
                    source_event_id=event.id,
                    payment_amount=event.amount,
                    deadline_date=PaymentTrackingService._deadline(structured, start_date, []),
                    destination_group_id=reminder_group_id,
                    target_userid=reminder_target,
                )
                source_message_time = ensure_aware(message.received_at) if message else event.created_at
                ReminderService(self.db).create_payment_confirmation_followups(
                    legal_case.id,
                    source_event_id=event.id,
                    start_at=source_message_time,
                    payment_type=structured.get("payment_type"),
                    payment_amount=event.amount,
                    destination_group_id=reminder_group_id,
                    target_userid=reminder_target,
                )
        elif event.event_type == "repayment_agreement":
            plan = metadata.get("structured_fields", {}).get("repayment_plan") or {}
            ReminderService(self.db).create_installment_reminders(
                legal_case.id,
                plan.get("installments") or [],
                source_event_id=event.id,
            )
        elif event.event_type == "keyword":
            text = event.extracted_text or ""
            from app.services.case_service import CaseService

            if any(keyword in text for keyword in ("已结清", "全部还清", "履行完毕", "双方就此再无纠纷")):
                CaseService(self.db).update_status(legal_case, "closed", reason="settlement_confirmed")
                ReminderService(self.db).cancel_pending_case_reminders(legal_case.id, "案件已确认结清")
            elif "强制执行" in text or "仲裁" in text:
                CaseService(self.db).mark_defaulted(legal_case)
            elif "逾期" in text:
                CaseService(self.db).mark_overdue(legal_case)
