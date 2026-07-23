import json
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attribution_item import AttributionItem
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.core.resource_permissions import (
    allowed_group_ids,
    allowed_tenant_ids,
    resource_scope_enabled,
    tenant_scope_enabled,
)
from app.services.case_group_service import CaseGroupService
from app.services.outbox_service import OutboxService
from app.utils.datetime_utils import now_tz


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
            reason=reason or ("群仅绑定一个有效案件" if suggested_case else "无法唯一确定案件"),
            evidence_json=json.dumps(evidence or {}, ensure_ascii=False, default=str),
            status="pending",
        )
        self.db.add(item)
        self.db.flush()
        return item

    def list(self, *, status: str | None = "pending", group_id: str | None = None, offset: int = 0, limit: int = 50, auth_context: dict | None = None) -> tuple[int, list[AttributionItem]]:
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
        return total, items

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
