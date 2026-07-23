import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.schemas.legal import MockMessageCreate
from app.services.case_service import CaseService
from app.services.case_candidate_service import CaseCandidateService
from app.services.attribution_service import AttributionService
from app.services.document_sync_service import DocumentSyncService
from app.services.media_file_service import MediaFileService
from app.services.merchant_question_service import MerchantQuestionService
from app.services.ocr_service import OCRService
from app.services.reminder_service import ReminderService
from app.services.tenant_settings_service import TenantSettingsService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import ensure_aware, now_tz, today_tz

logger = logging.getLogger(__name__)


class MessageService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.ocr_service = OCRService()
        self.case_service = CaseService(db)
        self.document_sync = DocumentSyncService(db)
        self.reminder_service = ReminderService(db)
        self.media_file_service = MediaFileService(db)

    def handle_mock_message(self, payload: MockMessageCreate) -> dict[str, Any]:
        return self.handle_incoming_message(payload)

    def handle_incoming_message(self, payload: MockMessageCreate) -> dict[str, Any]:
        group_message = self._save_group_message(payload)
        MerchantQuestionService(self.db).handle_message(group_message)
        extracted = self._extract(payload, group_message.tenant_id)
        legal_case = self.case_service.find_case_for_message(
            extracted.get("case_no"),
            group_message.group_id,
            group_message.tenant_id,
        )
        if not legal_case and extracted.get("case_no"):
            CaseCandidateService(self.db).detect(
                case_no=extracted.get("case_no"),
                group_id=group_message.group_id,
                tenant_id=group_message.tenant_id,
                source_type="text_message",
                source_message_id=group_message.id,
                extracted=extracted,
            )
        tenant_id = legal_case.tenant_id if legal_case else group_message.tenant_id
        if tenant_id and group_message.tenant_id != tenant_id:
            group_message.tenant_id = tenant_id
        # Media messages are classified after their bytes have been downloaded
        # and OCR has completed. Creating an eager unknown event here would
        # bypass the review gate and duplicate the media OCR event.
        event_types = [] if payload.msg_type in {"image", "file", "pdf"} else (extracted.get("event_types") or ["unknown"])

        event_ids: list[int] = []
        events_by_type: dict[str, LegalEvent] = {}
        for event_type in event_types:
            event = self._create_event(
                event_type=event_type,
                group_message_id=group_message.id,
                case_id=legal_case.id if legal_case else None,
                tenant_id=tenant_id,
                amount=extracted.get("amount"),
                extracted_text=extracted.get("extracted_text"),
                metadata=extracted.get("metadata") or {},
            )
            event_ids.append(event.id)
            events_by_type[event_type] = event
            if legal_case:
                event.attribution_status = "confirmed"
                event.business_status = "staged"
            else:
                event.attribution_status = "pending"
                event.business_status = "staged"
                AttributionService(self.db).ensure_event(event, group_id=group_message.group_id, reason="文本消息无法唯一确定案件")

        reminder_ids: list[int] = []

        self._handle_media_payload(group_message, payload, legal_case.id if legal_case else None)
        if payload.msg_type == "text" and extracted.get("case_no"):
            try:
                self.media_file_service.reanalyze_recent_pending_with_context(group_message, extracted.get("case_no"))
            except Exception:
                logger.exception("群聊补充案号触发材料重分析失败 group_message_id=%s", group_message.id)

        self.db.flush()
        return {
            "group_message_id": group_message.id,
            "case_id": legal_case.id if legal_case else None,
            "event_ids": event_ids,
            "reminder_ids": reminder_ids,
            "extracted": self._json_safe_extracted(extracted),
        }

    def _save_group_message(self, payload: MockMessageCreate) -> GroupMessage:
        received_at = ensure_aware(payload.received_at) if payload.received_at else now_tz()
        raw_payload_json = json.dumps(payload.raw_payload_json, ensure_ascii=False) if payload.raw_payload_json else payload.model_dump_json()
        tenant_id = payload.tenant_id or self._infer_tenant_id_from_group(payload.group_id)
        group_message = GroupMessage(
            group_id=payload.group_id,
            tenant_id=tenant_id,
            sender_id=payload.sender_id,
            msg_type=payload.msg_type,
            content=payload.content,
            file_url=payload.file_url,
            raw_payload_json=raw_payload_json,
            received_at=received_at,
        )
        self.db.add(group_message)
        self.db.flush()
        return group_message

    def _infer_tenant_id_from_group(self, group_id: str) -> str | None:
        legal_case = self.db.scalar(
            select(LegalCase)
            .where(LegalCase.group_id == group_id)
            .where(LegalCase.tenant_id.is_not(None))
            .order_by(LegalCase.id.asc())
        )
        return legal_case.tenant_id if legal_case else None

    def _extract(self, payload: MockMessageCreate, tenant_id: str | None) -> dict[str, Any]:
        if payload.msg_type == "text":
            return self.ocr_service.extract_from_text(payload.content, tenant_id=tenant_id)
        if payload.msg_type == "image":
            return self.ocr_service.extract_from_image(payload.file_url)
        if payload.msg_type in {"file", "pdf"}:
            return self.ocr_service.extract_from_pdf(payload.file_url)
        return {
            "case_no": None,
            "amounts": [],
            "amount": None,
            "keywords": [],
            "event_types": [],
            "extracted_text": payload.content or "",
            "metadata": {"parser": "unknown"},
        }

    def _create_event(
        self,
        event_type: str,
        group_message_id: int,
        case_id: int | None,
        tenant_id: str | None,
        amount: Decimal | None,
        extracted_text: str | None,
        metadata: dict[str, Any],
    ) -> LegalEvent:
        event = LegalEvent(
            case_id=case_id,
            tenant_id=tenant_id,
            group_message_id=group_message_id,
            event_type=event_type,
            event_time=now_tz(),
            amount=amount,
            extracted_text=extracted_text,
            metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        self.db.add(event)
        self.db.flush()
        return event

    def _json_safe_extracted(self, extracted: dict[str, Any]) -> dict[str, Any]:
        safe = dict(extracted)
        safe["amounts"] = [str(amount) for amount in extracted.get("amounts", [])]
        if extracted.get("amount") is not None:
            safe["amount"] = str(extracted["amount"])
        for key in ("event_time", "court_time"):
            if hasattr(safe.get(key), "isoformat"):
                safe[key] = safe[key].isoformat()
        return safe

    def _handle_media_payload(self, group_message: GroupMessage, payload: MockMessageCreate, case_id: int | None) -> None:
        if payload.msg_type not in {"image", "file", "pdf"}:
            return
        try:
            media_file = self.media_file_service.create_media_from_message(
                group_message,
                payload.model_dump(),
                case_id=case_id,
            )
            if media_file:
                self.media_file_service.download_media_file(media_file.id)
                if WeComArchiveGroupService(self.db).feature_enabled(group_message.group_id, "ocr"):
                    self.media_file_service.process_ocr(media_file.id)
        except Exception:
            # 媒体处理不能阻断消息入库和事件归档。
            logger.exception("媒体消息处理失败 group_message_id=%s", group_message.id)
            self.db.flush()

    def _payment_tracking_enabled(self, tenant_id: str | None, group_id: str) -> bool:
        effective = TenantSettingsService(self.db).get_effective_settings(tenant_id)
        return bool(effective["feature_flags"].get("enable_payment_tracking", True)) and WeComArchiveGroupService(self.db).feature_enabled(
            group_id,
            "payment_tracking",
        )
