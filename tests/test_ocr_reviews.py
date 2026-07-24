import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder


def _create_case(client):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": "(2026)黔0281民初3118号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "debtor_wecom_userid": "debtor_001",
            "lawyer_wecom_userid": "lawyer_001",
            "due_date": "2026-08-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def _replay_pdf(client, msgid: str, seq: int):
    response = client.post(
        "/api/v1/legal/wecom-archive/replay",
        json={
            "messages": [
                {
                    "seq": seq,
                    "msgid": msgid,
                    "roomid": "group_001",
                    "from": "merchant_001",
                    "msgtype": "file",
                    "file": {"filename": f"{msgid}.pdf", "md5sum": msgid, "filesize": 100},
                    "msgtime": 1780300000000,
                }
            ]
        },
    )
    assert response.status_code == 200


def _process_text(client, db_session, msgid: str, text: str) -> tuple[MediaFile, dict]:
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == msgid))
    assert media_file and media_file.local_path
    Path(media_file.local_path).with_suffix(".txt").write_text(text, encoding="utf-8")
    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")
    assert response.status_code == 200
    db_session.refresh(media_file)
    return media_file, response.json()["data"]


@pytest.fixture(autouse=True)
def use_local_text_ocr():
    os.environ["OCR_PROVIDER"] = "local_text"
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_pending_review_pauses_downstream_and_correction_runs_once(client, db_session):
    _create_case(client)
    _replay_pdf(client, "review_judgment", 801)
    media_file, data = _process_text(
        client,
        db_session,
        "review_judgment",
        "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n判决如下。",
    )

    assert data["review_status"] == "pending"
    assert data["business_applied"] is False
    assert media_file.review_event_id is not None
    assert db_session.get(LegalEvent, media_file.review_event_id) is not None
    assert db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "legal_document_upload")) is None

    decision = client.post(
        f"/api/v1/legal/ocr-reviews/{media_file.id}/decision",
        json={"decision": "corrected", "defendant": "张三", "note": "已核对原件"},
        headers={"X-Operator": "reviewer-a"},
    )
    assert decision.status_code == 200
    assert decision.json()["data"]["review"]["review_status"] == "corrected"
    assert decision.json()["data"]["review"]["business_applied_at"] is None
    first_count = len(list(db_session.scalars(select(DocumentSyncLog)).all()))

    repeated = client.post(
        f"/api/v1/legal/ocr-reviews/{media_file.id}/decision",
        json={"decision": "corrected", "defendant": "张三", "note": "重复提交"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["already_decided"] is True
    assert len(list(db_session.scalars(select(DocumentSyncLog)).all())) == first_count


def test_rejected_review_never_executes_business(client, db_session):
    _create_case(client)
    _replay_pdf(client, "review_reject", 802)
    media_file, _ = _process_text(client, db_session, "review_reject", "无法识别的普通附件")

    response = client.post(
        f"/api/v1/legal/ocr-reviews/{media_file.id}/decision",
        json={"decision": "rejected", "note": "不是法务材料"},
    )

    assert response.status_code == 200
    db_session.refresh(media_file)
    assert media_file.review_status == "rejected"
    assert media_file.business_applied_at is None
    assert db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "archive")) is None


def test_payment_completed_cancels_all_pending_tracking(client, db_session):
    case_id = _create_case(client)
    _replay_pdf(client, "payment_notice_review", 803)
    _process_text(
        client,
        db_session,
        "payment_notice_review",
        "案件(2026)黔0281民初3118号缴费通知：诉讼费400元",
    )
    pending = list(
        db_session.scalars(
            select(Reminder)
            .where(Reminder.case_id == case_id)
            .where(Reminder.reminder_type == "payment_tracking")
            .where(Reminder.status == "pending")
        ).all()
    )
    assert len(pending) == 0

    _replay_pdf(client, "payment_done_review", 804)
    _process_text(
        client,
        db_session,
        "payment_done_review",
        "案件(2026)黔0281民初3118号付款截图，支付成功人民币400元",
    )

    db_session.expire_all()
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.case_id == case_id)).all())
    payment_reminders = [item for item in reminders if item.reminder_type == "payment_tracking"]
    assert payment_reminders == []
    legal_case = db_session.get(LegalCase, case_id)
    assert str(legal_case.paid_amount) == "0.00"


def test_review_preview_rejects_path_outside_storage(client, db_session, tmp_path):
    _create_case(client)
    _replay_pdf(client, "review_preview", 805)
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "review_preview"))
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private")
    media_file.local_path = str(outside)
    db_session.commit()

    response = client.get(f"/api/v1/legal/media-files/{media_file.id}/content")

    assert response.status_code == 403


def test_review_detail_returns_ai_context_snapshot(client, db_session):
    _replay_pdf(client, "review_context", 806)
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "review_context"))
    context = [
        {
            "message_id": 123,
            "sender_id": "lawyer_001",
            "msg_type": "text",
            "content": "这是（2026）黔0281民初9001号的材料",
            "received_at": "2026-07-23T10:00:00+08:00",
            "position": "before",
        }
    ]
    media_file.ocr_result_json = json.dumps(
        {"case_no": "（2026）黔0281民初9001号", "context_messages": context},
        ensure_ascii=False,
    )
    media_file.ocr_status = "processed"
    media_file.review_status = "pending"
    db_session.commit()

    response = client.get(f"/api/v1/legal/ocr-reviews/{media_file.id}")

    assert response.status_code == 200
    assert response.json()["data"]["context_messages"] == context


def test_review_detail_returns_current_context_without_changing_ai_snapshot(client, db_session):
    _replay_pdf(client, "review_context_neighbor", 807)
    _replay_pdf(client, "review_context_historical", 808)
    neighbor = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "review_context_neighbor"))
    historical = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "review_context_historical"))
    neighbor.extracted_text = "补充案号：（2026）黔0281民初9001号"
    neighbor.ocr_status = "processed"
    historical.ocr_result_json = json.dumps({"case_no": None}, ensure_ascii=False)
    historical.ocr_status = "processed"
    historical.review_status = "pending"
    db_session.commit()

    response = client.get(f"/api/v1/legal/ocr-reviews/{historical.id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["context_messages"] == []
    assert len(data["available_context_messages"]) == 1
    assert "9001号" in data["available_context_messages"][0]["content"]
