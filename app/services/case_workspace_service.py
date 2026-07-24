import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case_group import CaseGroup
from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder


class CaseWorkspaceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, case_id: int) -> dict:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
        groups = list(self.db.scalars(select(CaseGroup).where(CaseGroup.case_id == case_id, CaseGroup.status == "active").order_by(CaseGroup.is_primary.desc(), CaseGroup.id.asc())).all())
        group_ids = [item.group_id for item in groups] or [legal_case.group_id]
        messages = list(self.db.scalars(select(GroupMessage).where(GroupMessage.group_id.in_(group_ids)).order_by(GroupMessage.received_at.desc()).limit(100)).all())
        media = list(self.db.scalars(select(MediaFile).where(MediaFile.case_id == case_id).order_by(MediaFile.id.desc()).limit(100)).all())
        events = list(self.db.scalars(select(LegalEvent).where(LegalEvent.case_id == case_id).order_by(LegalEvent.id.desc()).limit(100)).all())
        payments = list(self.db.scalars(select(PaymentRecord).where(PaymentRecord.case_id == case_id).order_by(PaymentRecord.id.desc()).limit(100)).all())
        reminders = list(self.db.scalars(select(Reminder).where(Reminder.case_id == case_id).order_by(Reminder.id.desc()).limit(100)).all())
        sync_logs = list(self.db.scalars(select(DocumentSyncLog).where(DocumentSyncLog.case_id == case_id).order_by(DocumentSyncLog.id.desc()).limit(100)).all())
        timeline = sorted(
            [
                *({"type": "message", "id": item.id, "at": item.received_at.isoformat(), "label": item.msg_type} for item in messages),
                *({"type": "event", "id": item.id, "at": item.created_at.isoformat(), "label": item.event_type} for item in events),
                *({"type": "payment", "id": item.id, "at": item.created_at.isoformat(), "label": item.record_type} for item in payments),
                *({"type": "reminder", "id": item.id, "at": item.created_at.isoformat(), "label": item.reminder_type} for item in reminders),
            ],
            key=lambda item: item["at"],
            reverse=True,
        )[:200]
        recognized_facts = []
        for event in events:
            try:
                metadata = json.loads(event.metadata_json or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            fields = metadata.get("structured_fields")
            if not isinstance(fields, dict) or not fields:
                continue
            recognized_facts.append(
                {
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "fields": fields,
                    "field_sources": metadata.get("field_sources") or {},
                    "confidence": str(event.confidence) if event.confidence is not None else None,
                    "review_status": event.business_status,
                    "created_at": event.created_at.isoformat(),
                }
            )
        return {
            "case": self._case(legal_case),
            "groups": [self._attrs(item, ("id", "group_id", "is_primary", "status", "source", "confirmed_at")) for item in groups],
            "messages": [self._attrs(item, ("id", "group_id", "sender_id", "msg_type", "content", "received_at")) for item in messages],
            "media": [self._attrs(item, ("id", "group_id", "media_type", "original_filename", "ocr_status", "review_status", "business_applied_at")) for item in media],
            "events": [self._attrs(item, ("id", "event_type", "amount", "attribution_status", "business_status", "event_time")) for item in events],
            "payments": [self._attrs(item, ("id", "record_type", "amount", "payment_date", "payer_name", "status", "created_at")) for item in payments],
            "reminders": [self._attrs(item, ("id", "reminder_type", "remind_at", "content", "target_userid", "status")) for item in reminders],
            "sync_logs": [self._attrs(item, ("id", "sync_type", "outcome", "external_doc_id", "external_row_index", "created_at")) for item in sync_logs],
            "audit_timeline": timeline,
            "recognized_facts": recognized_facts,
            "counts": {"groups": len(groups), "messages": len(messages), "media": len(media), "events": len(events), "payments": len(payments), "reminders": len(reminders), "sync_logs": len(sync_logs)},
        }

    @staticmethod
    def _attrs(item, names: tuple[str, ...]) -> dict:
        result = {}
        for name in names:
            value = getattr(item, name)
            result[name] = value.isoformat() if hasattr(value, "isoformat") else str(value) if name in {"amount"} and value is not None else value
        return result

    @staticmethod
    def _case(item: LegalCase) -> dict:
        names = ("id", "case_no", "debtor_name", "plaintiff_name", "court_name", "document_type", "filing_date", "enforcement_case_no", "responsible_contact_id", "lifecycle_stage", "due_date", "status", "total_amount", "paid_amount", "tenant_id")
        return CaseWorkspaceService._attrs(item, names)
