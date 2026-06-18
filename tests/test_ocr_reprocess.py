import os
from pathlib import Path

from sqlalchemy import select

from app.adapters.ocr_providers.local_text_provider import LocalTextOCRProvider
from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.services.ocr_service import OCRService


def use_local_text_ocr():
    os.environ["OCR_PROVIDER"] = "local_text"
    get_settings.cache_clear()


def create_case(client, case_no="(2026)黔0281民初3118号"):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": case_no,
            "debtor_name": "张三",
            "group_id": "group_001",
            "debtor_wecom_userid": "debtor_001",
            "lawyer_wecom_userid": "lawyer_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["id"]


def replay_pdf(client, seq=30, msgid="msg_ocr_pdf"):
    response = client.post(
        "/api/v1/legal/wecom-archive/replay",
        json={
            "messages": [
                {
                    "seq": seq,
                    "msgid": msgid,
                    "roomid": "group_001",
                    "from": "user_001",
                    "msgtype": "file",
                    "file": {"filename": f"{msgid}.pdf", "md5sum": "ocr", "filesize": 100},
                    "msgtime": 1780300000000,
                }
            ]
        },
    )
    assert response.status_code == 200


def get_media(db_session, msgid):
    return db_session.scalar(select(MediaFile).where(MediaFile.msg_id == msgid))


def write_ocr_text(media_file, text):
    txt_path = Path(media_file.local_path).with_suffix(".txt")
    txt_path.write_text(text, encoding="utf-8")
    return txt_path


def test_local_text_provider_reads_neighbor_txt(tmp_path):
    pdf_path = tmp_path / "a.pdf"
    txt_path = tmp_path / "a.txt"
    pdf_path.write_bytes(b"pdf")
    txt_path.write_text("案件(2026)黔0281民初3118号需要缴费400元", encoding="utf-8")

    result = LocalTextOCRProvider().extract(str(pdf_path), "pdf")

    assert result["success"] is True
    assert result["provider"] == "local_text"
    assert "需要缴费400元" in result["raw_text"]
    assert result["confidence"] == 0.9


def test_local_text_provider_missing_txt_fails(tmp_path):
    image_path = tmp_path / "a.jpg"
    image_path.write_bytes(b"jpg")

    result = LocalTextOCRProvider().extract(str(image_path), "image")

    assert result["success"] is False
    assert result["raw_text"] == ""
    assert "未找到同名 OCR 文本文件" in result["error"]


def test_ocr_service_extracts_case_no_and_amount_from_local_text(tmp_path):
    use_local_text_ocr()
    pdf_path = tmp_path / "a.pdf"
    txt_path = tmp_path / "a.txt"
    pdf_path.write_bytes(b"pdf")
    txt_path.write_text("案号：(2026)黔0281民初3118号 缴费金额：1,200.50元", encoding="utf-8")

    result = OCRService().extract_from_file(str(pdf_path), "pdf")

    assert result["success"] is True
    assert result["case_no"] == "(2026)黔0281民初3118号"
    assert str(result["amount"]) == "1200.50"
    assert result["event_type"] == "payment_notice"


def test_ocr_payment_notice_creates_legal_event(client, db_session):
    use_local_text_ocr()
    create_case(client)
    replay_pdf(client, seq=31, msgid="msg_notice_event")
    media_file = get_media(db_session, "msg_notice_event")
    write_ocr_text(media_file, "案件(2026)黔0281民初3118号需要缴费400元，7天内完成")

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["event_type"] == "payment_notice"
    assert data["matched_case_id"] is not None
    event = db_session.get(LegalEvent, data["event_id"])
    assert event.event_type == "payment_notice"
    assert str(event.amount) == "400.00"


def test_ocr_payment_notice_creates_7_tracking_reminders(client, db_session):
    use_local_text_ocr()
    create_case(client)
    replay_pdf(client, seq=32, msgid="msg_notice_reminders")
    media_file = get_media(db_session, "msg_notice_reminders")
    write_ocr_text(media_file, "案件(2026)黔0281民初3118号缴费通知：公告费400元")

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.json()["data"]["created_reminders"] == 7
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())
    assert len(reminders) == 7


def test_ocr_payment_done_increments_paid_amount(client, db_session):
    use_local_text_ocr()
    create_case(client)
    replay_pdf(client, seq=33, msgid="msg_paid_amount")
    media_file = get_media(db_session, "msg_paid_amount")
    write_ocr_text(media_file, "案件(2026)黔0281民初3118号付款截图，支付成功¥400")

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    legal_case = db_session.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初3118号"))
    assert str(legal_case.paid_amount) == "400.00"


def test_ocr_payment_done_writes_paid_amount_sync_log(client, db_session):
    use_local_text_ocr()
    create_case(client)
    replay_pdf(client, seq=34, msgid="msg_paid_log")
    media_file = get_media(db_session, "msg_paid_log")
    write_ocr_text(media_file, "案件(2026)黔0281民初3118号已支付人民币400")

    client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    sync_types = {log.sync_type for log in db_session.scalars(select(DocumentSyncLog)).all()}
    assert "paid_amount" in sync_types


def test_ocr_without_matching_case_still_writes_event_and_archive_log(client, db_session):
    use_local_text_ocr()
    replay_pdf(client, seq=35, msgid="msg_no_case")
    media_file = get_media(db_session, "msg_no_case")
    write_ocr_text(media_file, "案件(2026)黔0281民初9999号需要缴费400元")

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["matched_case_id"] is None
    event = db_session.get(LegalEvent, data["event_id"])
    assert event.case_id is None
    sync_types = {log.sync_type for log in db_session.scalars(select(DocumentSyncLog)).all()}
    assert "archive" in sync_types


def test_repeated_ocr_does_not_duplicate_payment_tracking_reminders(client, db_session):
    use_local_text_ocr()
    create_case(client)
    replay_pdf(client, seq=36, msgid="msg_notice_idempotent")
    media_file = get_media(db_session, "msg_notice_idempotent")
    write_ocr_text(media_file, "案件(2026)黔0281民初3118号诉讼费400元需要缴费")

    first = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")
    second = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert first.json()["data"]["created_reminders"] == 7
    assert second.json()["data"]["created_reminders"] == 0
    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())
    assert len(reminders) == 7
