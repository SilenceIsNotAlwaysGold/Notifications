from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok
from app.api.v1.response import raise_fail
from app.core.resource_permissions import allowed_tenant_ids, filter_by_case_or_group, has_case_access, has_group_access, has_reminder_access, has_tenant_data_access
from app.db.session import get_db
from app.models.reminder import Reminder
from app.schemas.legal import CustomReminderCreate, CustomReminderUpdate, ReminderCancel, ReminderListOut, ReminderOut, RunDueOut
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


@router.patch("/{reminder_id}")
def update_custom_reminder(
    reminder_id: int,
    payload: CustomReminderUpdate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    reminder = db.get(Reminder, reminder_id)
    if not reminder:
        raise_fail("提醒不存在", code=1404, status_code=404)
    if not has_reminder_access(db, operator_info, reminder):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        reminder = ReminderService(db).update_custom_reminder(
            reminder,
            remind_at=payload.remind_at,
            content=payload.content,
            target_userid=payload.target_userid,
            fields_set=payload.model_fields_set,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("自定义提醒更新成功", ReminderOut.model_validate(reminder))


@router.post("/{reminder_id}/cancel")
def cancel_reminder(
    reminder_id: int,
    payload: ReminderCancel,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    reminder = db.get(Reminder, reminder_id)
    if not reminder:
        raise_fail("提醒不存在", code=1404, status_code=404)
    if not has_reminder_access(db, operator_info, reminder):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        reminder = ReminderService(db).cancel_reminder(reminder, payload.reason, str(operator_info["operator"]))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("提醒已取消", ReminderOut.model_validate(reminder))


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
