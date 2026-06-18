import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.media_file import MediaFile
from app.models.operation_audit_log import OperationAuditLog
from app.models.reminder import Reminder
from app.services.api_key_service import ApiKeyService
from app.utils.datetime_utils import now_tz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_ADMIN_KEY = "env-admin-secret-001"


def _enable_auth(monkeypatch, resource_scope_enabled: bool = True):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RESOURCE_SCOPE_ENABLED", "true" if resource_scope_enabled else "false")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", "admin")
    get_settings.cache_clear()


def _create_key(db_session, role="legal", groups=None, cases=None):
    result = ApiKeyService(db_session).create_api_key(
        name=f"{role}-scoped",
        role=role,
        expires_at=None,
        created_by="test",
        allowed_group_ids=groups or [],
        allowed_case_ids=cases or [],
        allowed_tenant_ids=[],
    )
    db_session.commit()
    return result["api_key"]


def _case(db_session, case_no, group_id, due_date=None):
    legal_case = LegalCase(
        case_no=case_no,
        debtor_name="张三",
        group_id=group_id,
        due_date=due_date or date(2026, 6, 30),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        status="normal",
    )
    db_session.add(legal_case)
    db_session.commit()
    return legal_case


def test_create_api_key_with_allowed_group_ids(client, monkeypatch):
    _enable_auth(monkeypatch)
    response = client.post(
        "/api/v1/legal/api-keys",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"name": "法务A", "role": "legal", "allowed_group_ids": ["group_001"]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["allowed_group_ids"] == ["group_001"]


def test_api_key_list_hides_hash_and_returns_allowed_groups(client, monkeypatch):
    _enable_auth(monkeypatch)
    client.post(
        "/api/v1/legal/api-keys",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"name": "法务A", "role": "legal", "allowed_group_ids": ["group_001"]},
    )

    response = client.get("/api/v1/legal/api-keys", headers={"X-API-Key": ENV_ADMIN_KEY})

    body_text = response.text
    assert response.status_code == 200
    assert "key_hash" not in body_text
    assert response.json()["data"]["items"][0]["allowed_group_ids"] == ["group_001"]


def test_legal_key_only_lists_cases_in_allowed_groups(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _case(db_session, "(2026)黔0281民初7001号", "group_001")
    _case(db_session, "(2026)黔0281民初7002号", "group_002")
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["group_id"] == "group_001"


def test_legal_key_case_detail_outside_scope_returns_403(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    outside_case = _case(db_session, "(2026)黔0281民初7003号", "group_002")
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.get(f"/api/v1/legal/cases/{outside_case.id}", headers={"X-API-Key": key})

    assert response.status_code == 403


def test_legal_key_cannot_create_case_outside_allowed_group(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.post(
        "/api/v1/legal/cases",
        headers={"X-API-Key": key},
        json={
            "case_no": "(2026)黔0281民初7004号",
            "debtor_name": "张三",
            "group_id": "group_002",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )

    assert response.status_code == 403


def test_legal_key_can_create_custom_reminder_in_allowed_group(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.post(
        "/api/v1/legal/reminders/custom",
        headers={"X-API-Key": key},
        json={"group_id": "group_001", "remind_at": "2026-06-02T09:00:00+08:00", "content": "请跟进"},
    )

    assert response.status_code == 200


def test_media_files_list_filters_by_group_scope(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    db_session.add(MediaFile(group_id="group_001", media_type="image", download_status="downloaded", ocr_status="processed", source="mock"))
    db_session.add(MediaFile(group_id="group_002", media_type="image", download_status="downloaded", ocr_status="processed", source="mock"))
    db_session.commit()
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.get("/api/v1/legal/media-files", headers={"X-API-Key": key})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["group_id"] == "group_001"


def test_document_sync_logs_filter_by_case_scope(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    case_1 = _case(db_session, "(2026)黔0281民初7005号", "group_001")
    case_2 = _case(db_session, "(2026)黔0281民初7006号", "group_002")
    db_session.add(DocumentSyncLog(case_id=case_1.id, sync_type="status", request_payload_json="{}", response_payload_json="{}", status="success"))
    db_session.add(DocumentSyncLog(case_id=case_2.id, sync_type="status", request_payload_json="{}", response_payload_json="{}", status="success"))
    db_session.commit()
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.get("/api/v1/legal/document-sync-logs", headers={"X-API-Key": key})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1
    assert response.json()["data"]["items"][0]["case_id"] == case_1.id


def test_system_scoped_scan_status_only_scans_allowed_group(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    today = date(2026, 6, 2)
    case_1 = _case(db_session, "(2026)黔0281民初7007号", "group_001", due_date=today - timedelta(days=1))
    case_2 = _case(db_session, "(2026)黔0281民初7008号", "group_002", due_date=today - timedelta(days=1))
    key = _create_key(db_session, "system", groups=["group_001"])

    response = client.post("/api/v1/legal/cases/scan-status", headers={"X-API-Key": key})
    db_session.refresh(case_1)
    db_session.refresh(case_2)

    assert response.status_code == 200
    assert response.json()["data"]["scoped"] is True
    assert case_1.status == "overdue"
    assert case_2.status == "normal"


def test_audit_log_records_resource_scope_without_plain_key(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _case(db_session, "(2026)黔0281民初7009号", "group_001")
    key = _create_key(db_session, "legal", groups=["group_001"])

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200
    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/cases"))
    scope = json.loads(audit_log.resource_scope_json)
    assert scope["allowed_group_ids"]["items"] == ["group_001"]
    assert key not in (audit_log.resource_scope_json or "")


def test_resource_scope_disabled_skips_filter_but_keeps_rbac(client, db_session, monkeypatch):
    _enable_auth(monkeypatch, resource_scope_enabled=False)
    _case(db_session, "(2026)黔0281民初7010号", "group_001")
    _case(db_session, "(2026)黔0281民初7011号", "group_002")
    key = _create_key(db_session, "legal", groups=["group_001"])

    list_response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})
    audit_response = client.get("/api/v1/legal/operation-audit-logs", headers={"X-API-Key": key})

    assert list_response.status_code == 200
    assert list_response.json()["data"]["total"] == 2
    assert audit_response.status_code == 403


def test_env_admin_key_has_no_resource_scope_limit(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _case(db_session, "(2026)黔0281民初7012号", "group_001")
    _case(db_session, "(2026)黔0281民初7013号", "group_002")

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 2


def test_fifth_migration_file_exists():
    assert (PROJECT_ROOT / "alembic" / "versions" / "0005_add_api_key_resource_scopes.py").exists()
