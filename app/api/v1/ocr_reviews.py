import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_media_access
from app.db.session import get_db
from app.models.media_file import MediaFile
from app.schemas.legal import OCRReviewDecision, OCRReviewDecisionOut, OCRReviewListOut, OCRReviewOut
from app.services.media_file_service import MediaFileService

router = APIRouter(prefix="/legal/ocr-reviews", tags=["legal-ocr-reviews"])


def _parse_json(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _review_out(media_file: MediaFile) -> OCRReviewOut:
    return OCRReviewOut(
        media_file_id=media_file.id,
        tenant_id=media_file.tenant_id,
        case_id=media_file.case_id,
        group_id=media_file.group_id,
        msg_id=media_file.msg_id,
        media_type=media_file.media_type,
        original_filename=media_file.original_filename,
        mime_type=media_file.mime_type,
        ocr_status=media_file.ocr_status,
        review_status=media_file.review_status,
        event_id=media_file.review_event_id,
        extracted_text=media_file.extracted_text,
        ocr_result=_parse_json(media_file.ocr_result_json),
        final_result=_parse_json(media_file.review_result_json) if media_file.review_result_json else None,
        preview_url=f"/api/v1/legal/media-files/{media_file.id}/content" if media_file.local_path else None,
        reviewed_by=media_file.reviewed_by,
        reviewed_at=media_file.reviewed_at,
        review_note=media_file.review_note,
        business_applied_at=media_file.business_applied_at,
        created_at=media_file.created_at,
        updated_at=media_file.updated_at,
    )


@router.get("")
def list_ocr_reviews(
    review_status: str | None = None,
    group_id: str | None = None,
    tenant_id: str | None = None,
    case_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = MediaFileService(db).list_ocr_reviews(
        review_status=review_status,
        group_id=group_id,
        case_id=case_id,
        page=page,
        page_size=page_size,
    )
    if tenant_id:
        items = [item for item in items if item.tenant_id == tenant_id]
    items = filter_by_case_or_group(db, items, operator_info)
    return ok("OCR 复核列表查询成功", OCRReviewListOut(total=len(items), items=[_review_out(item) for item in items]))


@router.get("/{media_file_id}")
def get_ocr_review(
    media_file_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    media_file = db.get(MediaFile, media_file_id)
    if not media_file or not media_file.ocr_result_json:
        raise_fail("OCR 复核记录不存在", code=1404, status_code=404)
    if not has_media_access(db, operator_info, media_file):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    return ok("OCR 复核详情查询成功", _review_out(media_file))


@router.post("/{media_file_id}/decision")
def decide_ocr_review(
    media_file_id: int,
    payload: OCRReviewDecision,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    media_file = db.get(MediaFile, media_file_id)
    if not media_file:
        raise_fail("OCR 复核记录不存在", code=1404, status_code=404)
    if not has_media_access(db, operator_info, media_file):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    corrections = payload.model_dump(
        exclude={"decision", "note"},
        exclude_unset=True,
    )
    try:
        result = MediaFileService(db).decide_ocr_review(
            media_file_id,
            payload.decision,
            str(operator_info["operator"]),
            note=payload.note,
            corrections=corrections,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    data = OCRReviewDecisionOut(
        review=_review_out(result["media_file"]),
        already_decided=result["already_decided"],
        created_reminders=result["created_reminders"],
        cancelled_reminders=result["cancelled_reminders"],
    )
    return ok("OCR 复核处理完成", data)
