from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import allowed_group_ids, allowed_tenant_ids, filter_by_case_or_group, filter_cases, has_case_access, has_group_access, has_tenant_access, has_tenant_data_access
from app.db.session import get_db
from app.models.case_candidate import CaseCandidate
from app.models.legal_case import LegalCase
from app.schemas.legal import CaseCandidateConfirm, CaseCandidateConfirmOut, CaseCandidateListOut, CaseCandidateOut, CaseCandidateScanOut, CaseCreate, CaseLifecycleScanOut, CaseListOut, CaseOut, CaseUpdate, CaseUpdateOut
from app.services.case_candidate_service import CaseCandidateService
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
        CaseCandidateService(db).resolve_for_existing_case(legal_case, str(operator_info["operator"]))
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
    # Keep the read API compatible with admin pages opened before pagination was introduced.
    limit: int = Query(default=20, ge=1, le=200),
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


@router.get("/candidates")
def list_case_candidates(
    status: str | None = "pending",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = CaseCandidateService(db).list_candidates(status=status, page=page, page_size=page_size)
    items = filter_by_case_or_group(db, items, operator_info)
    return ok(
        "待确认案件查询成功",
        CaseCandidateListOut(total=len(items), items=[CaseCandidateOut.model_validate(item) for item in items]),
    )


@router.post("/candidates/scan")
def scan_case_candidates(
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    result = CaseCandidateService(db).scan_existing(
        group_ids=allowed_group_ids(operator_info) or None,
        tenant_ids=allowed_tenant_ids(operator_info) or None,
    )
    db.commit()
    return ok("历史资料扫描完成", CaseCandidateScanOut(**result))


@router.post("/candidates/{candidate_id}/confirm")
def confirm_case_candidate(
    candidate_id: int,
    payload: CaseCandidateConfirm,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    candidate = db.get(CaseCandidate, candidate_id)
    if not candidate:
        raise_fail("待确认案件不存在", code=1404, status_code=404)
    if not has_group_access(operator_info, candidate.group_id, candidate.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    if payload.tenant_id and not has_tenant_data_access(db, operator_info, payload.tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    if not has_group_access(operator_info, payload.group_id, payload.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        resolved, legal_case, backfill = CaseCandidateService(db).confirm(
            candidate_id,
            payload,
            str(operator_info["operator"]),
        )
        db.commit()
    except (IntegrityError, ValueError) as exc:
        db.rollback()
        raise_fail(str(exc) if isinstance(exc, ValueError) else "案件案号已存在", code=1001)
    return ok(
        "候选案件已确认建案",
        CaseCandidateConfirmOut(
            candidate=CaseCandidateOut.model_validate(resolved),
            case=CaseOut.model_validate(legal_case),
            **backfill,
        ),
    )


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_case_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    candidate = db.get(CaseCandidate, candidate_id)
    if not candidate:
        raise_fail("待确认案件不存在", code=1404, status_code=404)
    if not has_group_access(operator_info, candidate.group_id, candidate.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        candidate = CaseCandidateService(db).dismiss(candidate_id, str(operator_info["operator"]))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("候选案件已忽略", CaseCandidateOut.model_validate(candidate))


@router.get("/{case_id}")
def get_case(case_id: int, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    legal_case = db.get(LegalCase, case_id)
    if not legal_case:
        raise_fail("案件不存在", code=1404)
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    return ok("案件查询成功", CaseOut.model_validate(legal_case))


@router.patch("/{case_id}")
def update_case(
    case_id: int,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    legal_case = db.get(LegalCase, case_id)
    if not legal_case:
        raise_fail("案件不存在", code=1404)
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    tenant_id = payload.tenant_id if "tenant_id" in payload.model_fields_set else legal_case.tenant_id
    group_id = payload.group_id if "group_id" in payload.model_fields_set else legal_case.group_id
    if tenant_id and not has_tenant_data_access(db, operator_info, tenant_id):
        raise_fail("无权限访问该租户", code=403, status_code=403)
    if not has_group_access(operator_info, group_id, tenant_id):
        raise_fail("无权限访问目标群", code=403, status_code=403)
    try:
        result = CaseService(db).update_case(legal_case, payload)
        data = CaseUpdateOut(
            case=CaseOut.model_validate(result["case"]),
            updated_pending_reminders=result["updated_pending_reminders"],
            linked_media_files=result["linked_media_files"],
            linked_events=result["linked_events"],
            updated_group_messages=result["updated_group_messages"],
            backfill_skipped_reason=result["backfill_skipped_reason"],
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("案件绑定和成员信息已更新", data)
