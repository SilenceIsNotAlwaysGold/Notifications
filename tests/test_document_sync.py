import json
import os

import httpx
from sqlalchemy import select

from app.adapters.tencent_doc import TencentDocAdapter
from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.services.case_service import CaseService
from app.services.document_sync_service import DocumentSyncService


def reset_settings(**values):
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    get_settings.cache_clear()


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
    return response.json()["data"]["id"]


def test_mock_update_case_status_payload():
    reset_settings(TENCENT_DOC_MODE="mock")
    result = TencentDocAdapter().update_case_status("(2026)黔0281民初3118号", "defaulted", case_id=1)

    assert result["success"] is True
    assert result["mode"] == "mock"
    payload = result["request_payload"]
    assert payload["sheet_name"] == "案件台账"
    assert payload["row_match"] == {"案号": "(2026)黔0281民初3118号"}
    assert payload["fields"]["状态"] == "defaulted"


def test_mock_update_paid_amount_payload():
    reset_settings(TENCENT_DOC_MODE="mock")
    result = TencentDocAdapter().update_paid_amount("(2026)黔0281民初3118号", "400.00", case_id=1)

    assert result["success"] is True
    payload = result["request_payload"]
    assert payload["fields"]["已还金额"] == "400.00"
    assert payload["row_match"]["案号"] == "(2026)黔0281民初3118号"


def test_mock_append_archive_row_payload():
    reset_settings(TENCENT_DOC_MODE="mock")
    result = TencentDocAdapter().append_archive_row({"event_type": "payment_notice"}, case_id=1)

    assert result["success"] is True
    payload = result["request_payload"]
    assert payload["sheet_name"] == "资料台账"
    assert payload["row"]["event_type"] == "payment_notice"


def test_legal_event_creation_writes_archive_sync_log(client, db_session):
    create_case(client)
    client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号需要缴费400元",
        },
    )

    archive_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "archive"))
    assert archive_log is None


def test_payment_screenshot_ocr_writes_paid_amount_sync_log(client, db_session):
    os.environ["OCR_PROVIDER"] = "local_text"
    get_settings.cache_clear()
    create_case(client)
    response = client.post(
        "/api/v1/legal/wecom-archive/replay",
        json={
            "messages": [
                {
                    "seq": 51,
                    "msgid": "msg_sync_paid",
                    "roomid": "group_001",
                    "from": "user_001",
                    "msgtype": "file",
                    "file": {"filename": "msg_sync_paid.pdf", "md5sum": "abc", "filesize": 100},
                    "msgtime": 1780300000000,
                }
            ]
        },
    )
    assert response.status_code == 200
    from pathlib import Path
    from app.models.media_file import MediaFile

    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_sync_paid"))
    Path(media_file.local_path).with_suffix(".txt").write_text(
        "案件(2026)黔0281民初3118号付款截图，转账成功人民币400",
        encoding="utf-8",
    )
    client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    legal_case = db_session.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初3118号"))
    assert str(legal_case.paid_amount) == "0.00"
    sync_types = {log.sync_type for log in db_session.scalars(select(DocumentSyncLog)).all()}
    assert "paid_amount" not in sync_types


def test_status_update_writes_status_sync_log(client, db_session):
    case_id = create_case(client)
    legal_case = db_session.get(LegalCase, case_id)

    CaseService(db_session).mark_defaulted(legal_case)
    db_session.commit()

    status_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.sync_type == "status"))
    assert status_log is not None
    payload = json.loads(status_log.request_payload_json)
    assert payload["payload"]["fields"]["状态"] == "defaulted"


def test_document_sync_logs_query_api(client):
    create_case(client)
    client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初3118号需要缴费400元",
        },
    )

    response = client.get("/api/v1/legal/document-sync-logs", params={"sync_type": "archive"})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 0


def test_failed_sync_log_can_retry(client, db_session):
    log = DocumentSyncLog(
        case_id=None,
        sync_type="archive",
        sync_target="tencent_doc",
        external_sheet_name="资料台账",
        idempotency_key="retry-test",
        request_payload_json=json.dumps(
            {
                "operation": "append_archive_row",
                "payload": {"sheet_name": "资料台账", "row": {"event_type": "payment_notice"}},
            },
            ensure_ascii=False,
        ),
        response_payload_json="{}",
        status="failed",
        error_message="manual failure",
    )
    db_session.add(log)
    db_session.commit()

    response = client.post(f"/api/v1/legal/document-sync-logs/{log.id}/retry")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "applied"
    assert data["retry_count"] == 1


def test_kdocs_failed_log_retry_uses_real_gateway_without_leaking_token(client, db_session, monkeypatch):
    reset_settings(
        KDOCS_MODE="real",
        KDOCS_BASE_URL="https://kdocs-gateway.test",
        KDOCS_ACCESS_TOKEN="secret-token",
        KDOCS_SPACE_ID="space_001",
    )
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"success": True, "row_id": "row_retry_001"}, request=request)

    monkeypatch.setattr("app.adapters.kdocs.httpx.post", fake_post)
    payload = {
        "operation": "append_court_time_row",
        "payload": {
            "space_id": "space_001",
            "sheet_id": "致和法务/开庭时间",
            "sort_by": "开庭时间",
            "row": {"案号": "(2026)黔0281民初3118号", "开庭时间": "2026-07-02T15:00:00+08:00"},
        },
    }
    log = DocumentSyncLog(
        case_id=None,
        sync_type="court_time",
        sync_target="kdocs",
        external_sheet_name="致和法务/开庭时间",
        idempotency_key="kdocs-retry-test",
        request_payload_json=json.dumps(payload, ensure_ascii=False),
        response_payload_json='{"success": false}',
        status="failed",
        error_message="网关临时失败",
    )
    db_session.add(log)
    db_session.commit()

    response = client.post(f"/api/v1/legal/document-sync-logs/{log.id}/retry")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "applied"
    assert data["retry_count"] == 1
    assert captured["url"] == "https://kdocs-gateway.test/kdocs/append_court_time_row"
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert captured["json"]["row"]["案号"] == "(2026)黔0281民初3118号"
    assert "secret-token" not in data["request_payload_json"]
    assert "secret-token" not in data["response_payload_json"]


def test_real_mode_missing_token_or_sheet_id_returns_failure_without_crash():
    reset_settings(
        TENCENT_DOC_MODE="real",
        TENCENT_DOC_BASE_URL="https://example.test",
        TENCENT_DOC_ACCESS_TOKEN="",
        TENCENT_DOC_SHEET_ID="",
    )

    result = TencentDocAdapter().update_case_status("(2026)黔0281民初3118号", "overdue", case_id=1)

    assert result["success"] is False
    assert result["mode"] == "real"
    assert "TENCENT_DOC_ACCESS_TOKEN" in result["error"]
    assert "TENCENT_DOC_SHEET_ID" in result["error"]


def test_manual_case_snapshot_sync_api(client):
    case_id = create_case(client)

    response = client.post(f"/api/v1/legal/cases/{case_id}/sync")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_type"] == "case_snapshot"
    assert data["status"] == "applied"


class CountingKDocsAdapter:
    def __init__(self, fail: bool = False, final_filename: str | None = None):
        self.calls = 0
        self.fail = fail
        self.final_filename = final_filename

    def append_court_time_row(self, row, tenant_id=None):
        self.calls += 1
        payload = {"tenant_id": tenant_id, "sheet_id": "court-sheet", "row": row}
        return {
            "success": not self.fail,
            "sync_target": "kdocs",
            "operation": "append_court_time_row",
            "request_payload": payload,
            "response": {"row_id": "row-1"} if not self.fail else None,
            "error": "temporary failure" if self.fail else None,
        }


def test_duplicate_sync_returns_reserved_log_without_second_gateway_call(db_session):
    event = LegalEvent(event_type="court_notice", metadata_json="{}")
    db_session.add(event)
    db_session.flush()
    adapter = CountingKDocsAdapter()
    service = DocumentSyncService(db_session, adapter=adapter)
    row = {"案号": "(2026)黔0281民初3118号", "开庭时间": "2026-07-02T15:00:00+08:00"}

    first = service.sync_court_time(event, row)
    second = service.sync_court_time(event, row)

    assert first.id == second.id
    assert first.status == "applied"
    assert adapter.calls == 1
    assert len(list(db_session.scalars(select(DocumentSyncLog)).all())) == 1


def test_failed_sync_requires_retry_and_reuses_original_log(db_session):
    event = LegalEvent(event_type="court_notice", metadata_json="{}")
    db_session.add(event)
    db_session.flush()
    adapter = CountingKDocsAdapter(fail=True)
    service = DocumentSyncService(db_session, adapter=adapter)
    row = {"案号": "(2026)黔0281民初3118号", "开庭时间": "2026-07-02T15:00:00+08:00"}

    failed = service.sync_court_time(event, row)
    duplicate = service.sync_court_time(event, row)
    adapter.fail = False
    retried = service.retry_failed_sync(failed.id)

    assert duplicate.id == failed.id == retried.id
    assert retried.status == "applied"
    assert retried.retry_count == 1
    assert adapter.calls == 2
    assert len(list(db_session.scalars(select(DocumentSyncLog)).all())) == 1
