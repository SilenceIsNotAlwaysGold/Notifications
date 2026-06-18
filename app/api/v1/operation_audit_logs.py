from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.core.resource_permissions import allowed_tenant_ids, has_tenant_access
from app.db.session import get_db
from app.schemas.legal import OperationAuditLogListOut, OperationAuditLogOut
from app.services.operation_audit_log_service import OperationAuditLogService

router = APIRouter(prefix="/legal/operation-audit-logs", tags=["legal-operation-audit"])


@router.get("")
def list_operation_audit_logs(
    operator: str | None = None,
    action: str | None = None,
    path: str | None = None,
    tenant_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if tenant_id and not has_tenant_access(operator_info, tenant_id):
        return ok("查询成功", OperationAuditLogListOut(total=0, items=[]))
    scoped_tenants = allowed_tenant_ids(operator_info)
    total, items = OperationAuditLogService(db).list_logs(
        operator=operator,
        action=action,
        path=path,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )
    if not tenant_id and scoped_tenants:
        items = [item for item in items if item.tenant_id in scoped_tenants or item.tenant_id is None]
        total = len(items)
    data = OperationAuditLogListOut(total=total, items=[OperationAuditLogOut.model_validate(item) for item in items])
    return ok("查询成功", data)
