from decimal import Decimal
import json
import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.case_status_history import CaseStatusHistory
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.schemas.legal import CaseCreate, CaseUpdate
from app.services.document_sync_service import DocumentSyncService
from app.utils.datetime_utils import now_tz


class CaseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.document_sync = DocumentSyncService(db)

    def create_case(self, data: CaseCreate) -> LegalCase:
        values = data.model_dump()
        values["case_no"] = self.normalize_case_no(data.case_no)
        legal_case = LegalCase(**values, status="normal", paid_amount=Decimal("0.00"))
        self.db.add(legal_case)
        self.db.flush()
        return legal_case

    def list_cases(
        self,
        status: str | None = None,
        case_no: str | None = None,
        group_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[LegalCase]]:
        query = select(LegalCase)
        if status:
            query = query.where(LegalCase.status == status)
        if case_no:
            query = query.where(LegalCase.case_no.contains(case_no))
        if group_id:
            query = query.where(LegalCase.group_id == group_id)

        all_items = list(self.db.scalars(query.order_by(LegalCase.id.desc())).all())
        return len(all_items), all_items[offset : offset + limit]

    def find_case_by_case_no(self, case_no: str | None) -> LegalCase | None:
        if not case_no:
            return None
        normalized = self.normalize_case_no(case_no)
        variants = {
            normalized,
            normalized.replace("(", "（").replace(")", "）"),
        }
        return self.db.scalar(select(LegalCase).where(LegalCase.case_no.in_(variants)).order_by(LegalCase.id.asc()))

    @staticmethod
    def normalize_case_no(case_no: str) -> str:
        return re.sub(r"\s+", "", case_no.strip()).replace("（", "(").replace("）", ")")

    def find_case_for_message(
        self,
        case_no: str | None,
        group_id: str | None,
        tenant_id: str | None = None,
    ) -> LegalCase | None:
        legal_case = self.find_case_by_case_no(case_no)
        if legal_case or not group_id:
            return legal_case
        query = select(LegalCase).where(LegalCase.group_id == group_id)
        if tenant_id:
            query = query.where((LegalCase.tenant_id == tenant_id) | (LegalCase.tenant_id.is_(None)))
        matches = list(self.db.scalars(query.order_by(LegalCase.id.asc()).limit(2)).all())
        return matches[0] if len(matches) == 1 else None

    def update_case(self, legal_case: LegalCase, data: CaseUpdate) -> dict[str, object]:
        fields = data.model_fields_set
        if "total_amount" in fields and data.total_amount is not None and data.total_amount < legal_case.paid_amount:
            raise ValueError("总金额不能小于已还金额")
        required_fields = {"debtor_name", "group_id", "due_date", "total_amount"}
        for field in required_fields & fields:
            if getattr(data, field) is None:
                raise ValueError(f"{field} 不能为空")

        for field in fields:
            value = getattr(data, field)
            if isinstance(value, str):
                value = value.strip() or None
            if field in required_fields and value is None:
                raise ValueError(f"{field} 不能为空")
            setattr(legal_case, field, value)
        self.db.flush()

        updated_pending_reminders = self._update_pending_reminders(legal_case)
        backfill = self._backfill_group_data(legal_case) if fields & {"group_id", "tenant_id"} else self._empty_backfill()
        self.db.flush()
        return {
            "case": legal_case,
            "updated_pending_reminders": updated_pending_reminders,
            **backfill,
        }

    def _update_pending_reminders(self, legal_case: LegalCase) -> int:
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.case_id == legal_case.id)
                .where(Reminder.status == "pending")
                .order_by(Reminder.id.asc())
            ).all()
        )
        for reminder in reminders:
            reminder.group_id = legal_case.group_id
            reminder.tenant_id = legal_case.tenant_id
            if reminder.reminder_type == "repayment_before_due":
                reminder.target_userid = legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid
                reminder.content = f"还款提醒：案件 {legal_case.case_no} 将于 {legal_case.due_date} 到期，请及时跟进还款。"
            elif reminder.reminder_type in {"default_upgrade", "payment_tracking"}:
                reminder.target_userid = legal_case.lawyer_wecom_userid
        return len(reminders)

    def _backfill_group_data(self, legal_case: LegalCase) -> dict[str, object]:
        other_case_count = self.db.scalar(
            select(func.count(LegalCase.id))
            .where(LegalCase.group_id == legal_case.group_id)
            .where(LegalCase.id != legal_case.id)
        ) or 0
        if other_case_count:
            return {
                **self._empty_backfill(),
                "backfill_skipped_reason": "目标群已绑定多个案件，未自动关联历史材料",
            }

        group_message_ids = select(GroupMessage.id).where(GroupMessage.group_id == legal_case.group_id)
        updated_group_messages = 0
        if legal_case.tenant_id:
            group_message_result = self.db.execute(
                update(GroupMessage)
                .where(GroupMessage.group_id == legal_case.group_id)
                .where(GroupMessage.tenant_id.is_(None))
                .values(tenant_id=legal_case.tenant_id)
            )
            updated_group_messages = group_message_result.rowcount or 0

        media_values: dict[str, object] = {"case_id": legal_case.id}
        event_values: dict[str, object] = {"case_id": legal_case.id}
        if legal_case.tenant_id:
            media_values["tenant_id"] = legal_case.tenant_id
            event_values["tenant_id"] = legal_case.tenant_id
        media_result = self.db.execute(
            update(MediaFile)
            .where(MediaFile.group_id == legal_case.group_id)
            .where(MediaFile.case_id.is_(None))
            .values(**media_values)
        )
        event_result = self.db.execute(
            update(LegalEvent)
            .where(LegalEvent.group_message_id.in_(group_message_ids))
            .where(LegalEvent.case_id.is_(None))
            .values(**event_values)
        )
        return {
            "linked_media_files": media_result.rowcount or 0,
            "linked_events": event_result.rowcount or 0,
            "updated_group_messages": updated_group_messages,
            "backfill_skipped_reason": None,
        }

    @staticmethod
    def _empty_backfill() -> dict[str, object]:
        return {
            "linked_media_files": 0,
            "linked_events": 0,
            "updated_group_messages": 0,
            "backfill_skipped_reason": None,
        }

    def update_paid_amount(self, legal_case: LegalCase, amount: Decimal) -> LegalCase:
        legal_case.paid_amount = (legal_case.paid_amount or Decimal("0.00")) + amount
        if legal_case.paid_amount >= legal_case.total_amount:
            legal_case.paid_at = now_tz()
            self.update_status(legal_case, "paid", reason="fully_paid")
        self.document_sync.sync_paid_amount(legal_case)
        self.db.flush()
        return legal_case

    def mark_overdue(self, legal_case: LegalCase) -> LegalCase:
        legal_case.overdue_at = legal_case.overdue_at or now_tz()
        self.update_status(legal_case, "overdue", reason="overdue_scan")
        self.db.flush()
        return legal_case

    def mark_defaulted(self, legal_case: LegalCase) -> LegalCase:
        legal_case.defaulted_at = legal_case.defaulted_at or now_tz()
        self.update_status(legal_case, "defaulted", reason="default_upgrade")
        self.db.flush()
        return legal_case

    def update_status(
        self,
        legal_case: LegalCase,
        new_status: str,
        reason: str = "system",
        changed_by: str = "system",
        sync: bool = True,
    ) -> bool:
        old_status = legal_case.status
        if old_status == new_status:
            return False
        before = self._case_status_snapshot(legal_case)
        legal_case.status = new_status
        after = self._case_status_snapshot(legal_case)
        history = CaseStatusHistory(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            old_status=old_status,
            new_status=new_status,
            reason=reason,
            changed_by=changed_by,
            before_json=json.dumps(before, ensure_ascii=False, default=str),
            after_json=json.dumps(after, ensure_ascii=False, default=str),
        )
        self.db.add(history)
        if sync:
            self.document_sync.sync_status(legal_case, new_status)
        self.db.flush()
        return True

    @staticmethod
    def _case_status_snapshot(legal_case: LegalCase) -> dict[str, object]:
        return {
            "id": legal_case.id,
            "case_no": legal_case.case_no,
            "tenant_id": legal_case.tenant_id,
            "status": legal_case.status,
            "paid_amount": str(legal_case.paid_amount),
            "total_amount": str(legal_case.total_amount),
            "overdue_at": legal_case.overdue_at,
            "defaulted_at": legal_case.defaulted_at,
            "paid_at": legal_case.paid_at,
        }
