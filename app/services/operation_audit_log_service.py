from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operation_audit_log import OperationAuditLog


class OperationAuditLogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_logs(
        self,
        operator: str | None = None,
        action: str | None = None,
        path: str | None = None,
        tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[OperationAuditLog]]:
        query = select(OperationAuditLog)
        if operator:
            query = query.where(OperationAuditLog.operator == operator)
        if action:
            query = query.where(OperationAuditLog.action.contains(action))
        if path:
            query = query.where(OperationAuditLog.path.contains(path))
        if tenant_id:
            query = query.where(OperationAuditLog.tenant_id == tenant_id)
        items = list(self.db.scalars(query.order_by(OperationAuditLog.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]
