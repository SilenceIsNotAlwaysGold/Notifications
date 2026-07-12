from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_media_access
from app.models.media_file import MediaFile
from app.db.session import get_db
from app.schemas.legal import MediaFileListOut, MediaFileOut, MediaOCRResultOut
from app.services.media_file_service import MediaFileService

router = APIRouter(prefix="/legal/media-files", tags=["legal-media-files"])


@router.get("")
def list_media_files(
    group_id: str | None = None,
    tenant_id: str | None = None,
    case_id: int | None = None,
    media_type: str | None = None,
    download_status: str | None = None,
    ocr_status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = MediaFileService(db).list_media_files(
        group_id=group_id,
        case_id=case_id,
        media_type=media_type,
        download_status=download_status,
        ocr_status=ocr_status,
        page=page,
        page_size=page_size,
    )
    if tenant_id:
        items = [item for item in items if item.tenant_id == tenant_id]
    items = filter_by_case_or_group(db, items, operator_info)
    data = MediaFileListOut(total=len(items), items=[MediaFileOut.model_validate(item) for item in items])
    return ok("媒体文件查询成功", data)


@router.post("/{media_file_id}/download")
def download_media_file(media_file_id: int, db: Session = Depends(get_db)):
    try:
        media_file = MediaFileService(db).download_media_file(media_file_id)
        data = MediaFileOut.model_validate(media_file)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("媒体文件下载处理完成", data)


@router.post("/{media_file_id}/ocr")
def process_media_ocr(
    media_file_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, str] = Depends(get_current_operator),
):
    media_file = db.get(MediaFile, media_file_id)
    if media_file and not has_media_access(db, operator_info, media_file):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        result = MediaFileService(db).process_ocr(media_file_id, trigger_type="api", operator=operator_info["operator"])
        data = MediaOCRResultOut(
            media_file_id=result["media_file_id"],
            ocr_status=result["ocr_status"],
            event_id=result.get("event_id"),
            matched_case_id=result.get("matched_case_id"),
            event_type=result.get("event_type"),
            amount=result.get("amount"),
            document_type=result.get("document_type"),
            plaintiff=result.get("plaintiff"),
            defendant=result.get("defendant"),
            court_time=result.get("court_time"),
            requires_review=bool(result.get("requires_review")),
            created_reminders=result.get("created_reminders") or 0,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    if result.get("error"):
        return JSONResponse(
            status_code=400,
            content={
                "code": 1,
                "message": f"OCR处理失败：{result['error']}",
                "data": data.model_dump(),
            },
        )
    return ok("OCR 处理完成", data)
