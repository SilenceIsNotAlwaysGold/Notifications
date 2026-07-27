import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_media_access
from app.db.session import get_db
from app.models.media_file import MediaFile
from app.models.document_sync_log import DocumentSyncLog
from app.models.wecom_archive_group import WeComArchiveGroup
from app.schemas.legal import (
    CourtSummonsListOut,
    CourtSummonsOut,
    OCRReviewDecision,
    OCRReviewDecisionOut,
    OCRReviewListOut,
    OCRReviewOut,
)
from app.services.group_context_service import GroupContextService
from app.services.media_file_service import MediaFileService

router = APIRouter(prefix="/legal/ocr-reviews", tags=["legal-ocr-reviews"])


def _parse_json(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _review_out(
    media_file: MediaFile,
    *,
    available_context_messages: list[dict] | None = None,
) -> OCRReviewOut:
    ocr_result = _parse_json(media_file.ocr_result_json)
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
        context_messages=ocr_result.get("context_messages") or [],
        available_context_messages=available_context_messages or [],
        ocr_result=ocr_result,
        final_result=_parse_json(media_file.review_result_json) if media_file.review_result_json else None,
        preview_url=f"/api/v1/legal/media-files/{media_file.id}/content" if media_file.local_path else None,
        reviewed_by=media_file.reviewed_by,
        reviewed_at=media_file.reviewed_at,
        review_note=media_file.review_note,
        business_applied_at=media_file.business_applied_at,
        created_at=media_file.created_at,
        updated_at=media_file.updated_at,
    )


def _court_sync_logs(db: Session) -> tuple[dict[str, DocumentSyncLog], dict[int, DocumentSyncLog]]:
    by_msg_id: dict[str, DocumentSyncLog] = {}
    by_media_id: dict[int, DocumentSyncLog] = {}
    logs = db.scalars(
        select(DocumentSyncLog)
        .where(DocumentSyncLog.sync_type.in_(("court_time", "legal_document_upload")))
        .order_by(DocumentSyncLog.id.desc())
    ).all()
    for log in logs:
        payload = _parse_json(log.request_payload_json).get("payload") or {}
        row = payload.get("row") or {}
        msg_id = row.get("消息ID")
        if msg_id and msg_id not in by_msg_id:
            by_msg_id[str(msg_id)] = log
        metadata = payload.get("metadata") or {}
        media_file_id = metadata.get("media_file_id")
        if media_file_id is not None and int(media_file_id) not in by_media_id:
            by_media_id[int(media_file_id)] = log
    return by_msg_id, by_media_id


def _court_summons_out(
    media_file: MediaFile,
    *,
    group_name: str | None,
    sync_log: DocumentSyncLog | None,
) -> CourtSummonsOut:
    base = _review_out(media_file)
    result = base.final_result or base.ocr_result
    metadata = result.get("metadata") or {}
    detection_status = (
        "suspected"
        if metadata.get("court_summons_fallback") or result.get("event_type") != "court_notice"
        else "confirmed"
    )
    if media_file.review_status == "rejected":
        workflow_status = "rejected"
    elif sync_log and sync_log.status == "failed":
        workflow_status = "write_failed"
    elif media_file.business_applied_at is not None:
        workflow_status = "written"
    elif media_file.review_status == "pending" and not (
        (result.get("defendant") or "").strip() and result.get("court_time")
    ):
        workflow_status = "incomplete"
    elif media_file.review_status == "pending":
        workflow_status = "pending_review"
    else:
        workflow_status = "pending_write"
    return CourtSummonsOut(
        **base.model_dump(),
        group_name=group_name,
        detection_status=detection_status,
        workflow_status=workflow_status,
        sync_log_id=sync_log.id if sync_log else None,
        sync_status=sync_log.status if sync_log else None,
        external_row_index=sync_log.external_row_index if sync_log else None,
        sync_error=sync_log.error_message if sync_log else None,
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


@router.get("/court-summons")
def list_court_summons(
    workflow_status: str | None = Query(
        default=None,
        pattern="^(incomplete|pending_review|pending_write|written|write_failed|rejected)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, media_files = MediaFileService(db).list_court_summons(page=page, page_size=page_size)
    media_files = filter_by_case_or_group(db, media_files, operator_info)
    groups = db.scalars(select(WeComArchiveGroup)).all()
    group_names = {
        identifier: group.display_name
        for group in groups
        for identifier in (group.room_id, group.wecomapi_room_id)
        if identifier
    }
    logs_by_msg_id, logs_by_media_id = _court_sync_logs(db)
    items = [
        _court_summons_out(
            media_file,
            group_name=group_names.get(media_file.group_id),
            sync_log=logs_by_msg_id.get(media_file.msg_id or "") or logs_by_media_id.get(media_file.id),
        )
        for media_file in media_files
    ]
    if workflow_status:
        items = [item for item in items if item.workflow_status == workflow_status]
    return ok("开庭传票列表查询成功", CourtSummonsListOut(total=len(items), items=items))


@router.post("/court-summons/{media_file_id}/retry")
def retry_court_summons(
    media_file_id: int,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    media_file = db.get(MediaFile, media_file_id)
    if not media_file:
        raise_fail("开庭传票不存在", code=1404, status_code=404)
    if not has_media_access(db, operator_info, media_file):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        result = MediaFileService(db).retry_court_summons(media_file_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("开庭传票写入重试完成", _review_out(result))


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
    available_context = GroupContextService(db).around_message(media_file.group_message_id)
    return ok(
        "OCR 复核详情查询成功",
        _review_out(media_file, available_context_messages=available_context),
    )


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
