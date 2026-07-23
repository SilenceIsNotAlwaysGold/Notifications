import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case_candidate import CaseCandidate
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.services.ocr_service import OCRService
from app.schemas.legal import CaseCandidateConfirm, CaseCreate
from app.services.case_service import CaseService
from app.utils.datetime_utils import now_tz


class CaseCandidateService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.case_service = CaseService(db)

    def detect(
        self,
        *,
        case_no: str | None,
        group_id: str,
        tenant_id: str | None,
        source_type: str,
        extracted: dict[str, Any],
        source_message_id: int | None = None,
        source_media_file_id: int | None = None,
    ) -> CaseCandidate | None:
        if not case_no or not group_id:
            return None
        normalized = self.case_service.normalize_case_no(case_no)
        if self.case_service.find_case_by_case_no(normalized):
            return None

        if source_media_file_id is not None:
            stale_candidates = self.db.scalars(
                select(CaseCandidate)
                .where(CaseCandidate.source_media_file_id == source_media_file_id)
                .where(CaseCandidate.normalized_case_no != normalized)
                .where(CaseCandidate.status == "pending")
            ).all()
            for stale in stale_candidates:
                stale.status = "dismissed"
                stale.dismissed_by = "system:ocr-correction"
                stale.dismissed_at = now_tz()
                stale.updated_at = now_tz()

        candidate = self.db.scalar(select(CaseCandidate).where(CaseCandidate.normalized_case_no == normalized))
        detected_at = now_tz()
        values = self._suggested_values(extracted)
        if candidate is None:
            candidate = CaseCandidate(
                normalized_case_no=normalized,
                case_no=normalized,
                tenant_id=tenant_id,
                group_id=group_id,
                source_type=source_type,
                source_message_id=source_message_id,
                source_media_file_id=source_media_file_id,
                extracted_json=self._dump_extracted(extracted),
                first_detected_at=detected_at,
                last_detected_at=detected_at,
                **values,
            )
            self.db.add(candidate)
        else:
            candidate.occurrence_count += 1
            candidate.last_detected_at = detected_at
            candidate.updated_at = detected_at
            if candidate.status == "pending":
                candidate.tenant_id = tenant_id or candidate.tenant_id
                candidate.group_id = group_id or candidate.group_id
                candidate.source_type = source_type
                candidate.source_message_id = source_message_id or candidate.source_message_id
                candidate.source_media_file_id = source_media_file_id or candidate.source_media_file_id
                candidate.extracted_json = self._dump_extracted(extracted)
                for field, value in values.items():
                    if value is not None:
                        setattr(candidate, field, value)
        self.db.flush()
        return candidate

    def list_candidates(
        self,
        *,
        status: str | None = "pending",
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[int, list[CaseCandidate]]:
        query = select(CaseCandidate)
        if status:
            query = query.where(CaseCandidate.status == status)
        items = list(self.db.scalars(query.order_by(CaseCandidate.last_detected_at.desc(), CaseCandidate.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def scan_existing(
        self,
        *,
        group_ids: list[str] | None = None,
        tenant_ids: list[str] | None = None,
    ) -> dict[str, int]:
        media_query = select(MediaFile).where(MediaFile.case_id.is_(None)).where(MediaFile.ocr_result_json.is_not(None))
        message_query = select(GroupMessage).where(GroupMessage.msg_type == "text").where(GroupMessage.content.is_not(None))
        if group_ids:
            media_query = media_query.where(MediaFile.group_id.in_(group_ids))
            message_query = message_query.where(GroupMessage.group_id.in_(group_ids))
        if tenant_ids:
            media_query = media_query.where((MediaFile.tenant_id.in_(tenant_ids)) | (MediaFile.tenant_id.is_(None)))
            message_query = message_query.where((GroupMessage.tenant_id.in_(tenant_ids)) | (GroupMessage.tenant_id.is_(None)))

        media_items = list(self.db.scalars(media_query.order_by(MediaFile.id.desc())).all())
        message_items = list(self.db.scalars(message_query.order_by(GroupMessage.id.desc())).all())
        created = 0
        for media_file in media_items:
            extracted = self._load_extracted(media_file.review_result_json or media_file.ocr_result_json)
            if self._candidate_missing(extracted.get("case_no")):
                created += int(
                    self.detect(
                        case_no=extracted.get("case_no"),
                        group_id=media_file.group_id,
                        tenant_id=media_file.tenant_id,
                        source_type="media_ocr_backfill",
                        source_message_id=media_file.group_message_id,
                        source_media_file_id=media_file.id,
                        extracted=extracted,
                    )
                    is not None
                )

        extractor = OCRService()
        for message in message_items:
            extracted = extractor.extract_from_text(message.content, tenant_id=message.tenant_id)
            if self._candidate_missing(extracted.get("case_no")):
                created += int(
                    self.detect(
                        case_no=extracted.get("case_no"),
                        group_id=message.group_id,
                        tenant_id=message.tenant_id,
                        source_type="text_message_backfill",
                        source_message_id=message.id,
                        extracted=extracted,
                    )
                    is not None
                )
        self.db.flush()
        return {
            "scanned_media": len(media_items),
            "scanned_messages": len(message_items),
            "created_candidates": created,
        }

    def confirm(
        self,
        candidate_id: int,
        payload: CaseCandidateConfirm,
        operator: str,
    ) -> tuple[CaseCandidate, LegalCase, dict[str, object]]:
        candidate = self.db.get(CaseCandidate, candidate_id)
        if not candidate:
            raise ValueError("待确认案件不存在")
        if candidate.status != "pending":
            raise ValueError("该候选案件已处理")
        if self.case_service.find_case_by_case_no(candidate.case_no):
            raise ValueError("该案号已存在，请刷新案件列表")

        legal_case = self.case_service.create_case(
            CaseCreate(
                case_no=candidate.case_no,
                debtor_name=payload.debtor_name,
                tenant_id=payload.tenant_id or candidate.tenant_id,
                group_id=payload.group_id,
                debtor_wecom_userid=payload.debtor_wecom_userid,
                lawyer_wecom_userid=payload.lawyer_wecom_userid,
                due_date=payload.due_date,
                total_amount=payload.total_amount,
            )
        )
        backfill = self.case_service.backfill_group_data(legal_case)
        self.resolve_for_existing_case(legal_case, operator, candidate=candidate)
        self.db.flush()
        return candidate, legal_case, backfill

    def dismiss(self, candidate_id: int, operator: str) -> CaseCandidate:
        candidate = self.db.get(CaseCandidate, candidate_id)
        if not candidate:
            raise ValueError("待确认案件不存在")
        if candidate.status != "pending":
            raise ValueError("该候选案件已处理")
        candidate.status = "dismissed"
        candidate.dismissed_by = operator
        candidate.dismissed_at = now_tz()
        candidate.updated_at = now_tz()
        self.db.flush()
        return candidate

    def resolve_for_existing_case(
        self,
        legal_case: LegalCase,
        operator: str,
        *,
        candidate: CaseCandidate | None = None,
    ) -> CaseCandidate | None:
        normalized = self.case_service.normalize_case_no(legal_case.case_no)
        candidate = candidate or self.db.scalar(
            select(CaseCandidate).where(CaseCandidate.normalized_case_no == normalized)
        )
        if not candidate or candidate.status != "pending":
            return candidate
        candidate.status = "confirmed"
        candidate.confirmed_case_id = legal_case.id
        candidate.confirmed_by = operator
        candidate.confirmed_at = now_tz()
        candidate.updated_at = now_tz()
        self.db.flush()
        return candidate

    @staticmethod
    def _suggested_values(extracted: dict[str, Any]) -> dict[str, Any]:
        return {
            "debtor_name": CaseCandidateService._clean_text(extracted.get("defendant"), 128),
            "due_date": CaseCandidateService._date_value(extracted.get("due_date")),
            "total_amount": CaseCandidateService._decimal_value(extracted.get("amount")),
            "document_type": CaseCandidateService._clean_text(extracted.get("document_type"), 64),
            "confidence": CaseCandidateService._confidence_value(extracted.get("confidence")),
        }

    @staticmethod
    def _clean_text(value: Any, max_length: int) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned[:max_length] or None

    @staticmethod
    def _date_value(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _decimal_value(value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            amount = Decimal(str(value))
            return amount if amount >= 0 else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _confidence_value(value: Any) -> Decimal | None:
        confidence = CaseCandidateService._decimal_value(value)
        if confidence is None:
            return None
        return min(Decimal("1"), confidence)

    @staticmethod
    def _dump_extracted(extracted: dict[str, Any]) -> str:
        allowed = {
            key: extracted.get(key)
            for key in ["case_no", "defendant", "plaintiff", "amount", "due_date", "document_type", "event_type", "confidence"]
            if extracted.get(key) is not None
        }
        return json.dumps(allowed, ensure_ascii=False, default=str)

    def _candidate_missing(self, case_no: str | None) -> bool:
        if not case_no or self.case_service.find_case_by_case_no(case_no):
            return False
        normalized = self.case_service.normalize_case_no(case_no)
        return self.db.scalar(select(CaseCandidate.id).where(CaseCandidate.normalized_case_no == normalized)) is None

    @staticmethod
    def _load_extracted(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}
