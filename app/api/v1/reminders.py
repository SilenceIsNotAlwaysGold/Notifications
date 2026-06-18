from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.resource_permissions import allowed_tenant_ids, filter_by_case_or_group, has_case_access, has_group_access, has_tenant_data_access
from app.db.session import get_db
from app.schemas.legal import CustomReminderCreate, ReminderListOut, ReminderOut, RunDueOut
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/legal/reminders", tags=["legal-reminders"])


@router.post("/custom")
def create_custom_reminder(
    payload: CustomReminderCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if payload.case_id is not None:
        allowed = has_case_access(db, operator_info, payload.case_id)
    else:
        if payload.tenant_id is None:
            tenants = allowed_tenant_ids(operator_info)
            if len(tenants) == 1:
                payload.tenant_id = tenants[0]
        allowed = has_tenant_data_access(db, operator_info, payload.tenant_id) and has_group_access(operator_info, payload.group_id, payload.tenant_id)
    if not allowed:
        raise_fail("无权限访问该资源", code=403, status_code=403)
    reminder = ReminderService(db).create_custom_reminder(
        group_id=payload.group_id,
        remind_at=payload.remind_at,
        content=payload.content,
        target_userid=payload.target_userid,
        case_id=payload.case_id,
        tenant_id=payload.tenant_id,
    )
    db.commit()
    return ok("自定义提醒创建成功", ReminderOut.model_validate(reminder))


@router.post("/run-due")
def run_due_reminders(db: Session = Depends(get_db), operator_info: dict[str, str] = Depends(get_current_operator)):
    result = ReminderService(db).send_due_reminders(trigger_type="api", operator=operator_info["operator"])
    db.commit()
    return ok("到期提醒扫描完成", RunDueOut(**result))


@router.get("")
def list_reminders(
    status: str | None = None,
    reminder_type: str | None = None,
    group_id: str | None = None,
    tenant_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = ReminderService(db).list_reminders(
        status=status,
        reminder_type=reminder_type,
        group_id=group_id,
        offset=offset,
        limit=limit,
    )
    if tenant_id:
        items = [item for item in items if item.tenant_id == tenant_id]
    items = filter_by_case_or_group(db, items, operator_info)
    data = ReminderListOut(total=len(items), items=[ReminderOut.model_validate(item) for item in items])
    return ok("提醒查询成功", data)
