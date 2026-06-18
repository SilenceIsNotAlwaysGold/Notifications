from decimal import Decimal
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.case_status_history import CaseStatusHistory
from app.models.legal_case import LegalCase
from app.schemas.legal import CaseCreate
from app.services.document_sync_service import DocumentSyncService
from app.utils.datetime_utils import now_tz


class CaseService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.document_sync = DocumentSyncService(db)

    def create_case(self, data: CaseCreate) -> LegalCase:
        legal_case = LegalCase(**data.model_dump(), status="normal", paid_amount=Decimal("0.00"))
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
        return self.db.scalar(select(LegalCase).where(LegalCase.case_no == case_no))

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
