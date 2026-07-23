from sqlalchemy import select

from app.models.case_candidate import CaseCandidate
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile


def _send_new_case_message(client, content: str = "案件(2026)黔0281民初9551号需要缴费400元"):
    return client.post(
        "/api/v1/legal/messages/mock",
        json={
            "group_id": "group_candidate",
            "sender_id": "user_candidate",
            "msg_type": "text",
            "content": content,
        },
    )


def test_unknown_case_number_creates_deduplicated_candidate(client, db_session):
    first = _send_new_case_message(client)
    second = _send_new_case_message(client, "请跟进案件（2026）黔0281民初9551号")

    assert first.status_code == 200
    assert first.json()["data"]["case_id"] is None
    assert second.status_code == 200
    response = client.get("/api/v1/legal/cases/candidates")
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["case_no"] == "(2026)黔0281民初9551号"
    assert data["items"][0]["occurrence_count"] == 2
    assert data["items"][0]["source_type"] == "text_message"


def test_confirm_candidate_creates_case_and_backfills_group_data(client, db_session):
    _send_new_case_message(client)
    candidate = db_session.scalar(select(CaseCandidate))

    response = client.post(
        f"/api/v1/legal/cases/candidates/{candidate.id}/confirm",
        json={
            "debtor_name": "自动识别债务人",
            "group_id": "group_candidate",
            "due_date": "2026-09-30",
            "total_amount": "400.00",
            "lawyer_wecom_userid": "lawyer_candidate",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["candidate"]["status"] == "confirmed"
    assert data["case"]["case_no"] == "(2026)黔0281民初9551号"
    legal_case = db_session.scalar(select(LegalCase))
    message = db_session.scalar(select(GroupMessage))
    event = db_session.scalar(select(LegalEvent).where(LegalEvent.group_message_id == message.id))
    assert event.case_id is None
    assert client.get("/api/v1/legal/cases/candidates").json()["data"]["total"] == 0


def test_dismissed_candidate_does_not_reopen_on_repeat_detection(client, db_session):
    _send_new_case_message(client)
    candidate = db_session.scalar(select(CaseCandidate))

    response = client.post(f"/api/v1/legal/cases/candidates/{candidate.id}/dismiss", json={})
    _send_new_case_message(client)

    assert response.status_code == 200
    db_session.refresh(candidate)
    assert candidate.status == "dismissed"
    assert candidate.occurrence_count == 2
    assert client.get("/api/v1/legal/cases/candidates").json()["data"]["total"] == 0


def test_existing_case_number_does_not_create_candidate(client):
    create_response = client.post(
        "/api/v1/legal/cases",
        json={
            "case_no": "(2026)黔0281民初9551号",
            "debtor_name": "已有案件",
            "group_id": "group_candidate",
            "due_date": "2026-09-30",
            "total_amount": "400.00",
        },
    )
    message_response = _send_new_case_message(client)

    assert create_response.status_code == 200
    assert message_response.json()["data"]["case_id"] == create_response.json()["data"]["id"]
    assert client.get("/api/v1/legal/cases/candidates").json()["data"]["total"] == 0


def test_legal_role_can_list_and_confirm_candidates(client, db_session, monkeypatch):
    from app.core.config import get_settings
    from app.services.api_key_service import ApiKeyService

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    get_settings.cache_clear()
    key = ApiKeyService(db_session).create_api_key(name="candidate", role="legal", expires_at=None, created_by="test")["api_key"]
    db_session.commit()
    headers = {"X-API-Key": key}
    message = _send_new_case_message(client)
    assert message.status_code == 401

    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_settings.cache_clear()
    _send_new_case_message(client)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_settings.cache_clear()
    candidate = db_session.scalar(select(CaseCandidate))

    assert client.get("/api/v1/legal/cases/candidates", headers=headers).status_code == 200
    response = client.post(
        f"/api/v1/legal/cases/candidates/{candidate.id}/confirm",
        headers=headers,
        json={
            "debtor_name": "权限测试",
            "group_id": "group_candidate",
            "due_date": "2026-09-30",
            "total_amount": "400.00",
        },
    )
    assert response.status_code == 200
    get_settings.cache_clear()


def test_scan_existing_materials_is_idempotent(client, db_session):
    message = GroupMessage(
        group_id="group_history_text",
        sender_id="history_user",
        msg_type="text",
        content="历史案件(2026)黔0281民初9661号需要缴费300元",
        raw_payload_json="{}",
    )
    db_session.add(message)
    db_session.flush()
    media = MediaFile(
        group_message_id=message.id,
        group_id="group_history_media",
        media_type="pdf",
        source="wecom_archive",
        download_status="downloaded",
        ocr_status="processed",
        ocr_result_json='{"case_no":"(2026)黔0281民初9662号","defendant":"历史债务人","amount":"800.00","document_type":"判决书"}',
    )
    db_session.add(media)
    db_session.commit()

    first = client.post("/api/v1/legal/cases/candidates/scan", json={})
    second = client.post("/api/v1/legal/cases/candidates/scan", json={})

    assert first.status_code == 200
    assert first.json()["data"]["created_candidates"] == 2
    assert second.json()["data"]["created_candidates"] == 0
    candidates = list(db_session.scalars(select(CaseCandidate).order_by(CaseCandidate.case_no)).all())
    assert len(candidates) == 2
    assert all(candidate.occurrence_count == 1 for candidate in candidates)
    media_candidate = next(candidate for candidate in candidates if candidate.source_media_file_id == media.id)
    assert media_candidate.debtor_name == "历史债务人"
