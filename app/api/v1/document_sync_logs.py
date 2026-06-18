from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_case_access, has_sync_log_access
from app.models.document_sync_log import DocumentSyncLog
from app.db.session import get_db
from app.models.legal_case import LegalCase
from app.schemas.legal import DocumentSyncLogListOut, DocumentSyncLogOut
from app.services.document_sync_service import DocumentSyncService

router = APIRouter(prefix="/legal", tags=["legal-document-sync"])


@router.get("/document-sync-logs")
def list_document_sync_logs(
    status: str | None = None,
    sync_type: str | None = None,
    case_id: int | None = None,
    tenant_id: str | None = None,
    sync_target: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if case_id is not None and not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    _total, items = DocumentSyncService(db).list_logs(
        status=status,
        sync_type=sync_type,
        case_id=case_id,
        sync_target=sync_target,
        page=page,
        page_size=page_size,
    )
    if tenant_id:
        items = [item for item in items if item.tenant_id == tenant_id]
    items = filter_by_case_or_group(db, items, operator_info)
    data = DocumentSyncLogListOut(total=len(items), items=[DocumentSyncLogOut.model_validate(item) for item in items])
    return ok("同步日志查询成功", data)


@router.post("/document-sync-logs/{sync_log_id}/retry")
def retry_document_sync_log(
    sync_log_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, str] = Depends(get_current_operator),
):
    sync_log = db.get(DocumentSyncLog, sync_log_id)
    if sync_log and not has_sync_log_access(db, operator_info, sync_log):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        log = DocumentSyncService(db).retry_failed_sync(sync_log_id, operator=operator_info["operator"])
        data = DocumentSyncLogOut.model_validate(log)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("同步重试完成", data)


@router.post("/cases/{case_id}/sync")
def sync_case_snapshot(
    case_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    legal_case = db.get(LegalCase, case_id)
    if not legal_case:
        raise_fail("案件不存在", code=1404)
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    log = DocumentSyncService(db).sync_case_snapshot(legal_case)
    data = DocumentSyncLogOut.model_validate(log)
    db.commit()
    return ok("同步完成", data)
