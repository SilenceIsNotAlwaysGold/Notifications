from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.case_group import CaseGroup
from app.models.legal_case import LegalCase
from app.utils.datetime_utils import now_tz


class CaseGroupService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bind(self, legal_case: LegalCase, group_id: str, operator: str, *, primary: bool = False, source: str = "manual") -> CaseGroup:
        group_id = group_id.strip()
        existing = self.db.scalar(select(CaseGroup).where(CaseGroup.case_id == legal_case.id, CaseGroup.group_id == group_id))
        if existing:
            existing.status = "active"
            existing.is_primary = primary or existing.is_primary
            existing.confirmed_by = operator
            existing.confirmed_at = now_tz()
            existing.updated_at = now_tz()
            return existing
        if primary:
            self.db.execute(update(CaseGroup).where(CaseGroup.case_id == legal_case.id).values(is_primary=False))
        binding = CaseGroup(
            tenant_id=legal_case.tenant_id,
            case_id=legal_case.id,
            group_id=group_id,
            is_primary=primary,
            status="active",
            source=source,
            confirmed_by=operator,
        )
        self.db.add(binding)
        if primary:
            legal_case.group_id = group_id
        self.db.flush()
        return binding

    def unbind(self, binding_id: int) -> CaseGroup:
        binding = self.db.get(CaseGroup, binding_id)
        if not binding:
            raise ValueError("案件群绑定不存在")
        if binding.is_primary:
            raise ValueError("主群不能直接解绑，请先设置新的主群")
        binding.status = "inactive"
        binding.updated_at = now_tz()
        self.db.flush()
        return binding

    def unique_case_for_group(self, group_id: str, tenant_id: str | None = None) -> LegalCase | None:
        query = select(LegalCase).outerjoin(CaseGroup, CaseGroup.case_id == LegalCase.id).where(
            ((CaseGroup.group_id == group_id) & (CaseGroup.status == "active"))
            | (LegalCase.group_id == group_id)
        ).distinct()
        if tenant_id:
            query = query.where((LegalCase.tenant_id == tenant_id) | (LegalCase.tenant_id.is_(None)))
        matches = list(self.db.scalars(query.order_by(LegalCase.id.asc()).limit(2)).all())
        return matches[0] if len(matches) == 1 else None

    def group_case_count(self, group_id: str) -> int:
        return int(self.db.scalar(select(func.count(CaseGroup.id)).where(CaseGroup.group_id == group_id, CaseGroup.status == "active")) or 0)

    def list_for_case(self, case_id: int) -> list[CaseGroup]:
        return list(self.db.scalars(select(CaseGroup).where(CaseGroup.case_id == case_id, CaseGroup.status == "active").order_by(CaseGroup.is_primary.desc(), CaseGroup.id.asc())).all())
