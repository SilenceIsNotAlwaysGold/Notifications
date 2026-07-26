import json
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attribution_item import AttributionItem
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.wecomapi_room_cache import WeComApiRoomCache
from app.core.resource_permissions import (
    allowed_group_ids,
    allowed_tenant_ids,
    resource_scope_enabled,
    tenant_scope_enabled,
)
from app.services.case_group_service import CaseGroupService
from app.services.outbox_service import OutboxService
from app.services.group_context_service import GroupContextService
from app.utils.datetime_utils import now_tz
from app.utils.regex_parser import parse_legal_text
from app.utils.repayment_annotation import parse_repayment_annotation


class AttributionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.case_groups = CaseGroupService(db)

    def ensure_media(self, media: MediaFile, *, suggested_case: LegalCase | None = None, reason: str | None = None, evidence: dict | None = None) -> AttributionItem:
        return self._ensure(
            subject_type="media",
            subject_id=media.id,
            tenant_id=media.tenant_id,
            group_id=media.group_id,
            media_file_id=media.id,
            suggested_case=suggested_case,
            reason=reason,
            evidence=evidence,
        )

    def ensure_event(self, event: LegalEvent, *, group_id: str | None = None, suggested_case: LegalCase | None = None, reason: str | None = None) -> AttributionItem:
        if group_id is None and event.group_message_id:
            message = self.db.get(GroupMessage, event.group_message_id)
            group_id = message.group_id if message else None
        return self._ensure(
            subject_type="event",
            subject_id=event.id,
            tenant_id=event.tenant_id,
            group_id=group_id or "",
            event_id=event.id,
            suggested_case=suggested_case,
            reason=reason,
            evidence={"event_type": event.event_type},
        )

    def _ensure(self, *, subject_type: str, subject_id: int, tenant_id: str | None, group_id: str, media_file_id: int | None = None, event_id: int | None = None, suggested_case: LegalCase | None = None, reason: str | None = None, evidence: dict | None = None) -> AttributionItem:
        item = self.db.scalar(select(AttributionItem).where(AttributionItem.subject_type == subject_type, AttributionItem.subject_id == subject_id))
        if item:
            if suggested_case and item.status == "pending":
                item.suggested_case_id = suggested_case.id
            return item
        item = AttributionItem(
            tenant_id=tenant_id,
            group_id=group_id,
            subject_type=subject_type,
            subject_id=subject_id,
            media_file_id=media_file_id,
            event_id=event_id,
            suggested_case_id=suggested_case.id if suggested_case else None,
            confidence=100 if suggested_case else None,
            reason=reason or ("明确字段唯一匹配候选案件" if suggested_case else "无法唯一确定案件"),
            evidence_json=json.dumps(evidence or {}, ensure_ascii=False, default=str),
            status="pending",
        )
        self.db.add(item)
        self.db.flush()
        return item

    def list(self, *, status: str | None = "pending", group_id: str | None = None, offset: int = 0, limit: int = 50, auth_context: dict | None = None) -> tuple[int, list[dict]]:
        query = select(AttributionItem)
        if status:
            query = query.where(AttributionItem.status == status)
        if group_id:
            query = query.where(AttributionItem.group_id == group_id)
        auth_context = auth_context or {}
        if resource_scope_enabled(auth_context) and auth_context.get("role") != "admin":
            groups = allowed_group_ids(auth_context)
            if groups:
                query = query.where(AttributionItem.group_id.in_(groups))
        if tenant_scope_enabled(auth_context):
            tenants = allowed_tenant_ids(auth_context)
            if tenants:
                query = query.where(AttributionItem.tenant_id.in_(tenants))
        total = int(self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        items = list(self.db.scalars(query.order_by(AttributionItem.id.desc()).offset(offset).limit(limit)).all())
        return total, self._present(items)

    def detail(self, item: AttributionItem) -> dict:
        result = self._present([item])[0]
        result["context_messages"] = GroupContextService(self.db).around_message(result.get("source_message_id"))
        return result

    def _present(self, items: list[AttributionItem]) -> list[dict]:
        if not items:
            return []
        media_ids = {item.media_file_id for item in items if item.media_file_id}
        event_ids = {item.event_id for item in items if item.event_id}
        media = {row.id: row for row in self.db.scalars(select(MediaFile).where(MediaFile.id.in_(media_ids))).all()} if media_ids else {}
        event_ids.update(row.review_event_id for row in media.values() if row.review_event_id)
        events = {row.id: row for row in self.db.scalars(select(LegalEvent).where(LegalEvent.id.in_(event_ids))).all()} if event_ids else {}
        message_ids = {row.group_message_id for row in media.values() if row.group_message_id}
        message_ids.update(row.group_message_id for row in events.values() if row.group_message_id)
        messages = {row.id: row for row in self.db.scalars(select(GroupMessage).where(GroupMessage.id.in_(message_ids))).all()} if message_ids else {}
        group_ids = {item.group_id for item in items if item.group_id}
        archive_names = {
            row.room_id: row.display_name
            for row in self.db.scalars(select(WeComArchiveGroup).where(WeComArchiveGroup.room_id.in_(group_ids))).all()
            if row.display_name
        } if group_ids else {}
        room_names = {
            row.room_id: row.room_name
            for row in self.db.scalars(select(WeComApiRoomCache).where(WeComApiRoomCache.room_id.in_(group_ids))).all()
            if row.room_name
        } if group_ids else {}
        case_ids = {item.suggested_case_id for item in items if item.suggested_case_id}
        cases = {row.id: row for row in self.db.scalars(select(LegalCase).where(LegalCase.id.in_(case_ids))).all()} if case_ids else {}

        output: list[dict] = []
        for item in items:
            media_row = media.get(item.media_file_id)
            event = events.get(item.event_id or (media_row.review_event_id if media_row else None))
            message_id = (media_row.group_message_id if media_row else None) or (event.group_message_id if event else None)
            message = messages.get(message_id)
            media_result = self._json_dict(media_row.review_result_json or media_row.ocr_result_json) if media_row else {}
            event_metadata = self._json_dict(event.metadata_json) if event else {}
            event_parsed = parse_legal_text(event.extracted_text) if event and event.extracted_text else {}
            event_annotation = parse_repayment_annotation(event.extracted_text) if event and event.extracted_text else None
            metadata = dict(media_result.get("metadata") or event_metadata)
            repayment = metadata.get("repayment_annotation") or event_metadata.get("repayment_annotation") or event_annotation or {}
            structured = metadata.get("structured_fields") or event_metadata.get("structured_fields") or {}
            amount = media_result.get("amount") or (str(event.amount) if event and event.amount is not None else None) or repayment.get("amount")
            recognized = {
                "case_no": media_result.get("case_no") or event_parsed.get("case_no"),
                "plaintiff": media_result.get("plaintiff") or repayment.get("plaintiff") or event_parsed.get("plaintiff"),
                "defendant": media_result.get("defendant") or repayment.get("defendant") or event_parsed.get("defendant"),
                "amount": amount,
                "installment_sequence": structured.get("installment_sequence") or repayment.get("installment_sequence"),
                "document_type": media_result.get("document_type") or metadata.get("document_type") or event_parsed.get("document_type"),
                "court_time": media_result.get("court_time") or structured.get("court_time") or event_parsed.get("court_time"),
            }
            recognized = {key: value for key, value in recognized.items() if value not in (None, "", [])}
            candidate = cases.get(item.suggested_case_id)
            output.append({
                "id": item.id,
                "tenant_id": item.tenant_id,
                "group_id": item.group_id,
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "media_file_id": item.media_file_id,
                "event_id": item.event_id,
                "suggested_case_id": item.suggested_case_id,
                "assigned_case_id": item.assigned_case_id,
                "confidence": item.confidence,
                "reason": item.reason,
                "evidence_json": item.evidence_json,
                "status": item.status,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at,
                "created_at": item.created_at,
                "group_name": archive_names.get(item.group_id) or room_names.get(item.group_id),
                "source_message_id": message.id if message else None,
                "source_sender_id": message.sender_id if message else None,
                "source_received_at": message.received_at if message else None,
                "source_text": message.content if message else None,
                "media_type": media_row.media_type if media_row else None,
                "mime_type": media_row.mime_type if media_row else None,
                "original_filename": media_row.original_filename if media_row else None,
                "preview_url": f"/api/v1/legal/media-files/{media_row.id}/content" if media_row and media_row.local_path else None,
                "ocr_text": media_row.extracted_text if media_row else (event.extracted_text if event else None),
                "ocr_status": media_row.ocr_status if media_row else None,
                "review_status": media_row.review_status if media_row else None,
                "event_type": media_result.get("event_type") or (event.event_type if event else None),
                "amount": amount,
                "recognized_fields": recognized,
                "field_sources": metadata.get("field_sources") or {},
                "context_messages": [],
                "suggested_case_no": candidate.case_no if candidate else None,
                "suggested_case_party": candidate.debtor_name if candidate else None,
            })
        return output

    @staticmethod
    def _json_dict(raw: str | None) -> dict:
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def batch_confirm(self, item_ids: Sequence[int], case_id: int, operator: str) -> dict[str, int]:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
        items = list(self.db.scalars(select(AttributionItem).where(AttributionItem.id.in_(item_ids))).all())
        if len(items) != len(set(item_ids)):
            raise ValueError("部分待归属记录不存在")
        confirmed = queued = 0
        for item in items:
            if item.status == "confirmed" and item.assigned_case_id == case_id:
                continue
            if item.status != "pending":
                raise ValueError(f"待归属记录 {item.id} 已处理")
            self._assign(item, legal_case)
            item.status = "confirmed"
            item.assigned_case_id = case_id
            item.decided_by = operator
            item.decided_at = now_tz()
            confirmed += 1
            if item.event_id:
                queued += self._approve_if_ready(self.db.get(LegalEvent, item.event_id), operator)
            elif item.media_file_id:
                media = self.db.get(MediaFile, item.media_file_id)
                if media and media.review_event_id:
                    queued += self._approve_if_ready(self.db.get(LegalEvent, media.review_event_id), operator)
        self.db.flush()
        return {"confirmed": confirmed, "queued": queued}

    def batch_reject(self, item_ids: Sequence[int], operator: str, reason: str) -> int:
        items = list(self.db.scalars(select(AttributionItem).where(AttributionItem.id.in_(item_ids), AttributionItem.status == "pending")).all())
        for item in items:
            item.status = "rejected"
            item.reason = reason
            item.decided_by = operator
            item.decided_at = now_tz()
        self.db.flush()
        return len(items)

    def _assign(self, item: AttributionItem, legal_case: LegalCase) -> None:
        if item.media_file_id:
            media = self.db.get(MediaFile, item.media_file_id)
            if media:
                media.case_id = legal_case.id
                media.tenant_id = legal_case.tenant_id
                if media.review_event_id:
                    event = self.db.get(LegalEvent, media.review_event_id)
                    if event:
                        event.case_id = legal_case.id
                        event.tenant_id = legal_case.tenant_id
                        event.attribution_status = "confirmed"
        if item.event_id:
            event = self.db.get(LegalEvent, item.event_id)
            if event:
                event.case_id = legal_case.id
                event.tenant_id = legal_case.tenant_id
                event.attribution_status = "confirmed"

    def _approve_if_ready(self, event: LegalEvent | None, operator: str) -> int:
        if not event or not event.case_id or event.business_status in {"approved", "applied", "rejected"}:
            return 0
        metadata = json.loads(event.metadata_json or "{}")
        media = self.db.get(MediaFile, metadata.get("media_file_id")) if metadata.get("media_file_id") else None
        if media and media.review_status == "pending":
            return 0
        if event.event_type == "unknown":
            return 0
        event.business_status = "approved"
        event.approved_by = operator
        event.approved_at = now_tz()
        OutboxService(self.db).enqueue_event(event.id, event.tenant_id)
        return 1
