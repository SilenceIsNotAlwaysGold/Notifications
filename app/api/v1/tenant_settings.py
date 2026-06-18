from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import has_tenant_access
from app.db.session import get_db
from app.schemas.legal import EffectiveTenantSettingsOut, TenantSettingsIn, TenantSettingsOut
from app.services.tenant_service import TenantService
from app.services.tenant_settings_service import TenantSettingsService

router = APIRouter(prefix="/legal/tenants", tags=["legal-tenant-settings"])


@router.get("/{tenant_id}/settings")
def get_tenant_settings(
    tenant_id: str,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _ensure_tenant_access(db, operator_info, tenant_id)
    data = TenantSettingsService(db).get_settings_for_api(tenant_id)
    return ok("租户配置查询成功", TenantSettingsOut(**data))


@router.put("/{tenant_id}/settings")
def update_tenant_settings(
    tenant_id: str,
    payload: TenantSettingsIn,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _ensure_tenant_access(db, operator_info, tenant_id)
    service = TenantSettingsService(db)
    service.create_or_update_settings(tenant_id, payload, operator=str(operator_info["operator"]))
    db.commit()
    data = service.get_settings_for_api(tenant_id)
    return ok("租户配置保存成功", TenantSettingsOut(**data))


@router.delete("/{tenant_id}/settings")
def delete_tenant_settings(
    tenant_id: str,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _ensure_tenant_access(db, operator_info, tenant_id)
    TenantSettingsService(db).delete_settings(tenant_id)
    db.commit()
    data = TenantSettingsService(db).get_effective_settings(tenant_id, masked=True)
    return ok("租户配置已恢复全局继承", EffectiveTenantSettingsOut(**data))


def _ensure_tenant_access(db: Session, operator_info: dict[str, object], tenant_id: str) -> None:
    if not has_tenant_access(operator_info, tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    if not TenantService(db).get_tenant(tenant_id):
        raise_fail("租户不存在", code=1404)
