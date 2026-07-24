from decimal import Decimal
import json
import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.case_status_history import CaseStatusHistory
from app.models.case_group import CaseGroup
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.schemas.legal import CaseCreate, CaseUpdate
from app.services.document_sync_service import DocumentSyncService
from app.services.case_group_service import CaseGroupService
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
        CaseGroupService(self.db).bind(legal_case, legal_case.group_id, "system:create-case", primary=True, source="case_create")
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
        return CaseGroupService(self.db).unique_case_for_group(group_id, tenant_id)

    def find_case_for_extracted(
        self,
        case_no: str | None,
        group_id: str | None,
        tenant_id: str | None = None,
        *,
        plaintiff: str | None = None,
        defendant: str | None = None,
    ) -> LegalCase | None:
        by_number = self.find_case_by_case_no(case_no)
        if by_number or not group_id:
            return by_number
        if defendant:
            query = (
                select(LegalCase)
                .outerjoin(CaseGroup, CaseGroup.case_id == LegalCase.id)
                .where(
                    ((CaseGroup.group_id == group_id) & (CaseGroup.status == "active"))
                    | (LegalCase.group_id == group_id)
                )
                .distinct()
            )
            if tenant_id:
                query = query.where((LegalCase.tenant_id == tenant_id) | (LegalCase.tenant_id.is_(None)))
            candidates = list(self.db.scalars(query.order_by(LegalCase.id.asc())).all())
            party_matches = [
                item
                for item in candidates
                if self._same_party(item.debtor_name, defendant)
                and (not plaintiff or not item.plaintiff_name or self._same_party(item.plaintiff_name, plaintiff))
            ]
            if len(party_matches) == 1:
                return party_matches[0]
        return CaseGroupService(self.db).unique_case_for_group(group_id, tenant_id)

    @staticmethod
    def _same_party(left: str | None, right: str | None) -> bool:
        normalize = lambda value: re.sub(r"[\s()（）,，。·]", "", value or "")
        return bool(normalize(left)) and normalize(left) == normalize(right)

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

    def backfill_group_data(self, legal_case: LegalCase) -> dict[str, object]:
        return self._backfill_group_data(legal_case)

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
        return {
            **self._empty_backfill(),
            "backfill_skipped_reason": "历史材料已进入待归属队列，需人工批量确认",
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
        from app.services.payment_service import PaymentService

        PaymentService(self.db).create(legal_case, amount=amount, status="approved", operator="legacy:update-paid-amount")
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
