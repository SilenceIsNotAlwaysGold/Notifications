from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.wecom_archive import WeComArchiveAdapter
from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import has_group_access
from app.db.session import get_db
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.schemas.legal import (
    CaseCreate,
    WeComArchiveDemoReplayOut,
    WeComArchiveGroupCreate,
    WeComArchiveGroupListOut,
    WeComArchiveGroupOut,
    WeComArchiveGroupUpdate,
    WeComArchivePullOut,
    WeComArchiveReplayRequest,
    WeComArchiveReplayWithOcrOut,
    WeComArchiveReplayWithOcrRequest,
)
from app.services.case_service import CaseService
from app.services.media_file_service import MediaFileService
from app.services.wecom_archive_group_service import WeComArchiveGroupService

router = APIRouter(prefix="/legal/wecom-archive", tags=["legal-wecom-archive"])


@router.get("/groups")
def list_wecom_archive_groups(
    status: str | None = None,
    tenant_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    try:
        _total, groups = WeComArchiveGroupService(db).list_groups(
            status=status,
            tenant_id=tenant_id,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    groups = [group for group in groups if has_group_access(operator_info, group.room_id, group.tenant_id)]
    return ok(
        "归档群查询成功",
        WeComArchiveGroupListOut(
            total=len(groups),
            items=[WeComArchiveGroupOut.model_validate(group) for group in groups],
        ),
    )


@router.post("/groups")
def create_wecom_archive_group(
    payload: WeComArchiveGroupCreate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    if not has_group_access(operator_info, payload.room_id, payload.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        group = WeComArchiveGroupService(db).create_group(payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("归档群创建成功", WeComArchiveGroupOut.model_validate(group))


@router.patch("/groups/{room_id}")
def update_wecom_archive_group(
    room_id: str,
    payload: WeComArchiveGroupUpdate,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    existing = WeComArchiveGroupService(db).get_group(room_id)
    if not existing:
        raise_fail("归档群不存在", code=1404, status_code=404)
    if not has_group_access(operator_info, existing.room_id, existing.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    try:
        group = WeComArchiveGroupService(db).update_group(room_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1404)
    return ok("归档群更新成功", WeComArchiveGroupOut.model_validate(group))


@router.post("/pull")
def pull_wecom_archive(db: Session = Depends(get_db), operator_info: dict[str, str] = Depends(get_current_operator)):
    result = WeComArchiveAdapter().pull_and_process(db, trigger_type="api", operator=operator_info["operator"])
    db.commit()
    return ok("拉取完成", WeComArchivePullOut(**result))


@router.post("/replay")
def replay_wecom_archive(payload: WeComArchiveReplayRequest, db: Session = Depends(get_db)):
    result = WeComArchiveAdapter(mock_messages=payload.messages).replay_messages(db, payload.messages)
    db.commit()
    return ok("回放完成", WeComArchivePullOut(**result))


@router.post("/replay-with-ocr")
def replay_wecom_archive_with_ocr(
    payload: WeComArchiveReplayWithOcrRequest,
    db: Session = Depends(get_db),
    operator_info: dict[str, str] = Depends(get_current_operator),
):
    result = WeComArchiveAdapter(mock_messages=payload.messages).replay_messages(db, payload.messages)
    ocr_summary = _apply_mock_ocr_texts(db, payload.ocr_text_by_msgid, operator_info["operator"])
    db.commit()
    return ok(
        "回放和OCR处理完成",
        WeComArchiveReplayWithOcrOut(
            **result,
            **ocr_summary,
        ),
    )


@router.post("/replay-demo")
def replay_wecom_archive_demo(
    db: Session = Depends(get_db),
    operator_info: dict[str, str] = Depends(get_current_operator),
):
    case_no = "(2026)黔0281民初3118号"
    legal_case = db.scalar(select(LegalCase).where(LegalCase.case_no == case_no))
    if not legal_case:
        try:
            legal_case = CaseService(db).create_case(
                CaseCreate(
                    case_no=case_no,
                    debtor_name="张三",
                    group_id="group_001",
                    debtor_wecom_userid="debtor_001",
                    lawyer_wecom_userid="lawyer_001",
                    due_date="2026-06-30",
                    total_amount="1000.00",
                )
            )
            db.flush()
        except IntegrityError:
            db.rollback()
            legal_case = db.scalar(select(LegalCase).where(LegalCase.case_no == case_no))

    messages = [
        _file_message(1001, "msg_demo_judgment", "判决书.pdf"),
        _file_message(1002, "msg_demo_court", "开庭传票.pdf"),
        _file_message(1003, "msg_demo_payment_notice", "缴费通知.pdf"),
        _file_message(1004, "msg_demo_payment_done", "付款截图.pdf"),
    ]
    ocr_text_by_msgid = {
        "msg_demo_judgment": "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三\n判决如下。",
        "msg_demo_court": "传票\n案号：(2026)黔0281民初3118号\n被告：张三\n定于2026年7月2日 下午3点开庭。",
        "msg_demo_payment_notice": "案件(2026)黔0281民初3118号缴费通知：诉讼费400元，7天内完成。",
        "msg_demo_payment_done": "案件(2026)黔0281民初3118号付款截图，支付成功人民币400。",
    }
    result = WeComArchiveAdapter(mock_messages=messages).replay_messages(db, messages)
    ocr_summary = _apply_mock_ocr_texts(db, ocr_text_by_msgid, operator_info["operator"])
    db.commit()
    return ok(
        "演示数据回放完成",
        WeComArchiveDemoReplayOut(
            **result,
            **ocr_summary,
            case_id=legal_case.id,
            case_no=case_no,
        ),
    )


def _apply_mock_ocr_texts(db: Session, ocr_text_by_msgid: dict[str, str], operator: str) -> dict[str, object]:
    ocr_results: list[dict[str, object]] = []
    ocr_processed = 0
    ocr_failed = 0
    media_service = MediaFileService(db)

    for msgid, ocr_text in ocr_text_by_msgid.items():
        media_file = db.scalar(select(MediaFile).where(MediaFile.msg_id == msgid).order_by(MediaFile.id.desc()))
        if not media_file:
            ocr_failed += 1
            ocr_results.append({"msgid": msgid, "success": False, "error": "未找到对应媒体文件"})
            continue
        if not media_file.local_path:
            media_file = media_service.download_media_file(media_file.id)
        if not media_file.local_path:
            ocr_failed += 1
            ocr_results.append({"msgid": msgid, "success": False, "media_file_id": media_file.id, "error": "媒体文件未下载"})
            continue
        txt_path = Path(media_file.local_path).with_suffix(".txt")
        txt_path.write_text(ocr_text, encoding="utf-8")
        ocr_result = media_service.process_ocr(media_file.id, trigger_type="api", operator=operator)
        success = not ocr_result.get("error")
        ocr_processed += 1 if success else 0
        ocr_failed += 0 if success else 1
        ocr_results.append(
            {
                "msgid": msgid,
                "success": success,
                "media_file_id": media_file.id,
                "ocr_status": ocr_result.get("ocr_status"),
                "event_type": ocr_result.get("event_type"),
                "document_type": ocr_result.get("document_type"),
                "plaintiff": ocr_result.get("plaintiff"),
                "defendant": ocr_result.get("defendant"),
                "court_time": ocr_result.get("court_time"),
                "requires_review": ocr_result.get("requires_review"),
                "matched_case_id": ocr_result.get("matched_case_id"),
                "created_reminders": ocr_result.get("created_reminders"),
                "error": ocr_result.get("error"),
                "txt_path": str(txt_path),
            }
        )
    return {"ocr_processed": ocr_processed, "ocr_failed": ocr_failed, "ocr_results": ocr_results}


def _file_message(seq: int, msgid: str, filename: str) -> dict[str, object]:
    return {
        "seq": seq,
        "msgid": msgid,
        "roomid": "group_001",
        "from": "user_001",
        "msgtype": "file",
        "file": {"filename": filename, "md5sum": "demo", "filesize": 100},
        "msgtime": 1780300000000,
    }
