from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import has_tenant_data_access
from app.db.session import get_db
from app.models.reminder_rule import ReminderRule
from app.schemas.legal import ReminderRuleCreate, ReminderRuleListOut, ReminderRuleOut, ReminderRuleUpdate
from app.services.reminder_rule_service import ReminderRuleService

router = APIRouter(prefix="/legal/reminder-rules", tags=["legal-reminder-rules"])


@router.get("")
def list_reminder_rules(
    tenant_id: str | None = None,
    rule_type: str | None = None,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if tenant_id and not has_tenant_data_access(db, operator_info, tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    rules = ReminderRuleService(db).list_rules(tenant_id=tenant_id, rule_type=rule_type)
    rules = [rule for rule in rules if has_tenant_data_access(db, operator_info, rule.tenant_id)]
    db.commit()
    return ok("提醒规则查询成功", ReminderRuleListOut(total=len(rules), items=[ReminderRuleOut.model_validate(rule) for rule in rules]))


@router.post("")
def create_reminder_rule(
    payload: ReminderRuleCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if not has_tenant_data_access(db, operator_info, payload.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        rule = ReminderRuleService(db).create_rule(payload)
        db.commit()
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "同一客户下提醒规则名称不能重复"
        raise_fail(message, code=1400)
    return ok("提醒规则创建成功", ReminderRuleOut.model_validate(rule))


@router.patch("/{rule_id}")
def update_reminder_rule(
    rule_id: int,
    payload: ReminderRuleUpdate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    existing = db.get(ReminderRule, rule_id)
    if not existing:
        raise_fail("提醒规则不存在", code=1404, status_code=404)
    if not has_tenant_data_access(db, operator_info, existing.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        rule, rebuilt = ReminderRuleService(db).update_rule(rule_id, payload)
        db.commit()
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "同一客户下提醒规则名称不能重复"
        raise_fail(message, code=1400)
    return ok("提醒规则更新成功", {"rule": ReminderRuleOut.model_validate(rule), "rebuilt_pending": rebuilt})
