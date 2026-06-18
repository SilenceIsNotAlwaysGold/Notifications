from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import allowed_tenant_ids, filter_cases, has_case_access, has_group_access, has_tenant_access, has_tenant_data_access
from app.db.session import get_db
from app.models.legal_case import LegalCase
from app.schemas.legal import CaseCreate, CaseLifecycleScanOut, CaseListOut, CaseOut
from app.services.case_lifecycle_service import CaseLifecycleService
from app.services.case_service import CaseService

router = APIRouter(prefix="/legal/cases", tags=["legal-cases"])


@router.post("")
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if payload.tenant_id is None:
        tenants = allowed_tenant_ids(operator_info)
        if len(tenants) == 1:
            payload.tenant_id = tenants[0]
    if payload.tenant_id and not has_tenant_data_access(db, operator_info, payload.tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    if not has_group_access(operator_info, payload.group_id, payload.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    service = CaseService(db)
    try:
        legal_case = service.create_case(payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise_fail("案件案号已存在", code=1001)
    return ok("案件创建成功", CaseOut.model_validate(legal_case))


@router.get("")
def list_cases(
    status: str | None = None,
    case_no: str | None = None,
    group_id: str | None = None,
    tenant_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = CaseService(db).list_cases(
        status=status,
        case_no=case_no,
        group_id=group_id,
        offset=offset,
        limit=limit,
    )
    if tenant_id:
        items = [item for item in items if item.tenant_id == tenant_id and has_tenant_access(operator_info, tenant_id)]
    items = filter_cases(items, operator_info, db)
    data = CaseListOut(total=len(items), items=[CaseOut.model_validate(item) for item in items])
    return ok("案件查询成功", data)


@router.post("/scan-status")
def scan_case_statuses(db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    result = CaseLifecycleService(db).scan_cases(trigger_type="api", operator=str(operator_info["operator"]), auth_context=operator_info)
    db.commit()
    return ok("案件状态扫描完成", CaseLifecycleScanOut(**result))


@router.get("/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    legal_case = db.get(LegalCase, case_id)
    if not legal_case:
        raise_fail("案件不存在", code=1404)
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    return ok("案件查询成功", CaseOut.model_validate(legal_case))
