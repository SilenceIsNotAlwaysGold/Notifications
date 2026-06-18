from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import allowed_tenant_ids, has_tenant_access
from app.db.session import get_db
from app.schemas.legal import TenantCreate, TenantListOut, TenantOut, TenantUpdate
from app.services.tenant_service import TenantService

router = APIRouter(prefix="/legal/tenants", tags=["legal-tenants"])


@router.post("")
def create_tenant(payload: TenantCreate, db: Session = Depends(get_db)):
    try:
        tenant = TenantService(db).create_tenant(payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_fail("租户 ID 已存在", code=1601)
    return ok("租户创建成功", TenantOut.model_validate(tenant))


@router.get("")
def list_tenants(
    status: str | None = None,
    tenant_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if tenant_id and not has_tenant_access(operator_info, tenant_id):
        return ok("租户查询成功", TenantListOut(total=0, items=[]))
    _total, items = TenantService(db).list_tenants(status=status, tenant_id=tenant_id, page=page, page_size=page_size)
    tenants = allowed_tenant_ids(operator_info)
    if tenants:
        items = [item for item in items if item.tenant_id in tenants]
    return ok("租户查询成功", TenantListOut(total=len(items), items=[TenantOut.model_validate(item) for item in items]))


@router.get("/{tenant_id}")
def get_tenant(tenant_id: str, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_tenant_access(operator_info, tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    tenant = TenantService(db).get_tenant(tenant_id)
    if not tenant:
        raise_fail("租户不存在", code=1404)
    return ok("租户查询成功", TenantOut.model_validate(tenant))


@router.patch("/{tenant_id}")
def update_tenant(tenant_id: str, payload: TenantUpdate, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_tenant_access(operator_info, tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    try:
        tenant = TenantService(db).update_tenant(tenant_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("租户更新成功", TenantOut.model_validate(tenant))


@router.post("/{tenant_id}/disable")
def disable_tenant(tenant_id: str, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_tenant_access(operator_info, tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    try:
        tenant = TenantService(db).disable_tenant(tenant_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("租户已禁用", TenantOut.model_validate(tenant))
