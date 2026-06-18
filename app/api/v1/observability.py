from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.resource_permissions import allowed_tenant_ids, has_case_access, has_reminder_access, has_tenant_access
from app.db.session import get_db
from app.models.reminder import Reminder
from app.models.case_status_history import CaseStatusHistory
from app.models.reminder_send_log import ReminderSendLog
from app.schemas.legal import (
    CaseStatusHistoryListOut,
    CaseStatusHistoryOut,
    ReminderSendLogListOut,
    ReminderSendLogOut,
    SystemRunLogListOut,
    SystemRunLogOut,
)
from app.services.system_run_log_service import SystemRunLogService

router = APIRouter(prefix="/legal", tags=["legal-observability"])


@router.get("/system-run-logs")
def list_system_run_logs(
    run_type: str | None = None,
    trigger_type: str | None = None,
    status: str | None = None,
    tenant_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if tenant_id and not has_tenant_access(operator_info, tenant_id):
        return ok("查询成功", SystemRunLogListOut(total=0, items=[]))
    scoped_tenants = allowed_tenant_ids(operator_info)
    total, items = SystemRunLogService(db).list_run_logs(
        run_type=run_type,
        trigger_type=trigger_type,
        status=status,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )
    if not tenant_id and scoped_tenants:
        items = [item for item in items if item.tenant_id in scoped_tenants or item.tenant_id is None]
        total = len(items)
    data = SystemRunLogListOut(total=total, items=[SystemRunLogOut.model_validate(item) for item in items])
    return ok("查询成功", data)


@router.get("/cases/{case_id}/status-histories")
def list_case_status_histories(
    case_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    query = select(CaseStatusHistory).where(CaseStatusHistory.case_id == case_id).order_by(CaseStatusHistory.id.desc())
    items = list(db.scalars(query).all())
    start = (page - 1) * page_size
    data = CaseStatusHistoryListOut(
        total=len(items),
        items=[CaseStatusHistoryOut.model_validate(item) for item in items[start : start + page_size]],
    )
    return ok("查询成功", data)


@router.get("/reminders/{reminder_id}/send-logs")
def list_reminder_send_logs(
    reminder_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    reminder = db.get(Reminder, reminder_id)
    if reminder and not has_reminder_access(db, operator_info, reminder):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    query = select(ReminderSendLog).where(ReminderSendLog.reminder_id == reminder_id).order_by(ReminderSendLog.id.desc())
    items = list(db.scalars(query).all())
    start = (page - 1) * page_size
    data = ReminderSendLogListOut(
        total=len(items),
        items=[ReminderSendLogOut.model_validate(item) for item in items[start : start + page_size]],
    )
    return ok("查询成功", data)
