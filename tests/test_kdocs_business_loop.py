import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile


def create_case(client):
    response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": "(2026)黔0281民初3118号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "debtor_wecom_userid": "debtor_001",
            "lawyer_wecom_userid": "lawyer_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )
    assert response.status_code == 200


def replay_pdf(client, msgid: str, filename: str = "文书.pdf"):
    response = client.post(
        "/api/v1/legal/wecom-archive/replay",
        json={
            "messages": [
                {
                    "seq": 200,
                    "msgid": msgid,
                    "roomid": "group_001",
                    "from": "user_001",
                    "msgtype": "file",
                    "file": {"filename": filename, "md5sum": "abc", "filesize": 100},
                    "msgtime": 1780300000000,
                }
            ]
        },
    )
    assert response.status_code == 200


def process_with_text(client, db_session, msgid: str, text: str):
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == msgid))
    assert media_file is not None
    Path(media_file.local_path).with_suffix(".txt").write_text(text, encoding="utf-8")

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    return media_file


@pytest.fixture(autouse=True)
def use_local_text_ocr():
    os.environ["OCR_PROVIDER"] = "local_text"
    os.environ["KDOCS_MODE"] = "mock"
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_judgment_uploads_renamed_file_and_writes_enforcement_row(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_judgment", "判决书.pdf")

    process_with_text(
        client,
        db_session,
        "msg_judgment",
        "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三\n判决如下。",
    )

    logs = list(db_session.scalars(select(DocumentSyncLog)).all())
    upload_log = next(log for log in logs if log.sync_type == "legal_document_upload")
    enforcement_log = next(log for log in logs if log.sync_type == "enforcement_progress")
    upload_payload = json.loads(upload_log.request_payload_json)["payload"]
    enforcement_row = json.loads(enforcement_log.request_payload_json)["payload"]["row"]

    assert upload_log.sync_target == "kdocs"
    assert upload_payload["target_filename"] == "李四-张三{判决书}.pdf"
    assert upload_payload["folder_id"] == "致和法务/判决书文件"
    assert enforcement_row["文书类型"] == "判决书"
    assert enforcement_row["原告"] == "李四"
    assert enforcement_row["被告"] == "张三"
    assert enforcement_row["文件名"] == "李四-张三{判决书}.pdf"


def test_media_ocr_api_returns_structured_review_fields(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_ocr_api", "判决书.pdf")
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_ocr_api"))
    assert media_file is not None
    Path(media_file.local_path).with_suffix(".txt").write_text(
        "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三",
        encoding="utf-8",
    )

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["event_type"] == "judgment"
    assert data["document_type"] == "判决书"
    assert data["plaintiff"] == "李四"
    assert data["defendant"] == "张三"
    assert data["requires_review"] is False


def test_judgment_missing_party_is_marked_for_review(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_review", "判决书.pdf")

    process_with_text(
        client,
        db_session,
        "msg_review",
        "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n判决如下。",
    )

    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_review"))
    enforcement_log = db_session.scalar(
        select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "enforcement_progress")
    )
    assert media_file.review_status == "pending"
    assert media_file.business_applied_at is None
    assert enforcement_log is None


@pytest.mark.parametrize(
    ("msgid", "doc_type", "text"),
    [
        ("msg_mediation", "调解书", "民事调解书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三"),
        ("msg_ruling", "裁定书", "民事裁定书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三"),
    ],
)
def test_mediation_and_ruling_keep_document_type(client, db_session, msgid, doc_type, text):
    create_case(client)
    replay_pdf(client, msgid, f"{doc_type}.pdf")

    process_with_text(client, db_session, msgid, text)

    enforcement_log = db_session.scalar(
        select(DocumentSyncLog)
        .where(DocumentSyncLog.sync_type == "enforcement_progress")
        .order_by(DocumentSyncLog.id.desc())
    )
    row = json.loads(enforcement_log.request_payload_json)["payload"]["row"]
    assert row["文书类型"] == doc_type
    assert row["文件名"] == f"李四-张三{{{doc_type}}}.pdf"


def test_court_summons_writes_court_time_row(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_court", "开庭传票.pdf")

    process_with_text(
        client,
        db_session,
        "msg_court",
        "传票\n案号：(2026)黔0281民初3118号\n被告：张三\n定于2026年7月2日 下午3点开庭。",
    )

    court_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "court_time"))
    row = json.loads(court_log.request_payload_json)["payload"]["row"]
    assert court_log.external_sheet_name == "致和法务/开庭时间"
    assert row["开庭时间"] == "2026-07-02T15:00:00+08:00"


def test_payment_notice_registers_payment_and_keeps_tracking(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_payment", "缴费通知.pdf")

    process_with_text(client, db_session, "msg_payment", "案件(2026)黔0281民初3118号缴费通知：诉讼费400元")

    payment_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "payment_registration"))
    row = json.loads(payment_log.request_payload_json)["payload"]["row"]
    assert row["缴费类型"] == "缴费通知"
    assert row["金额"] == "400.00"

    from app.models.reminder import Reminder

    reminders = list(db_session.scalars(select(Reminder).where(Reminder.reminder_type == "payment_tracking")).all())
    assert len(reminders) == 7


def test_payment_screenshot_registers_and_updates_paid_amount(client, db_session):
    create_case(client)
    replay_pdf(client, "msg_paid", "付款截图.pdf")

    process_with_text(client, db_session, "msg_paid", "案件(2026)黔0281民初3118号付款截图，支付成功人民币400")

    payment_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "payment_registration"))
    row = json.loads(payment_log.request_payload_json)["payload"]["row"]
    legal_case = db_session.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初3118号"))
    assert row["缴费类型"] == "付款完成"
    assert str(legal_case.paid_amount) == "400.00"


def test_kdocs_failure_writes_failed_log_without_losing_event(client, db_session):
    os.environ["KDOCS_MODE"] = "real"
    os.environ["KDOCS_BASE_URL"] = ""
    os.environ["KDOCS_ACCESS_TOKEN"] = ""
    os.environ["KDOCS_SPACE_ID"] = ""
    get_settings.cache_clear()
    create_case(client)
    replay_pdf(client, "msg_kdocs_fail", "判决书.pdf")

    process_with_text(
        client,
        db_session,
        "msg_kdocs_fail",
        "民事判决书\n案号：(2026)黔0281民初3118号\n原告：李四\n被告：张三",
    )

    failed_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.status == "failed"))
    assert failed_log is not None
    assert "KDOCS_BASE_URL" in failed_log.error_message


def test_kdocs_real_config_missing_is_reported():
    os.environ["KDOCS_MODE"] = "real"
    os.environ["KDOCS_BASE_URL"] = ""
    os.environ["KDOCS_ACCESS_TOKEN"] = ""
    os.environ["KDOCS_SPACE_ID"] = ""
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert any("KDOCS_MODE=real" in message for message in result["errors"])
