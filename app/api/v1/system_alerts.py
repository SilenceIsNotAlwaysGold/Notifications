from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import allowed_tenant_ids
from app.db.session import get_db
from app.schemas.legal import SystemAlertListOut, SystemAlertOut
from app.services.system_alert_service import SystemAlertService

router = APIRouter(prefix="/legal/system-alerts", tags=["legal-system-alerts"])


@router.get("")
def list_system_alerts(
    status: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    total, items = SystemAlertService(db).list_alerts(
        status=status,
        alert_type=alert_type,
        severity=severity,
        page=page,
        page_size=page_size,
    )
    scoped_tenants = allowed_tenant_ids(operator_info)
    if scoped_tenants:
        items = [item for item in items if item.tenant_id in scoped_tenants or item.tenant_id is None]
        total = len(items)
    return ok(
        "系统告警查询成功",
        SystemAlertListOut(total=total, items=[SystemAlertOut.model_validate(item) for item in items]),
    )


@router.post("/{alert_id}/ack")
def acknowledge_system_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    try:
        alert = SystemAlertService(db).acknowledge(alert_id, str(operator_info["operator"]))
    except ValueError as exc:
        raise_fail(str(exc), code=1404, status_code=404)
    db.commit()
    return ok("系统告警已确认", SystemAlertOut.model_validate(alert))


@router.post("/scan")
def scan_system_alerts(db: Session = Depends(get_db)):
    result = SystemAlertService(db).scan()
    db.commit()
    return ok("系统告警扫描完成", result)
