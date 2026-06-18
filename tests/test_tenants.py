import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.group_message import GroupMessage
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.operation_audit_log import OperationAuditLog
from app.models.tenant import Tenant
from app.services.api_key_service import ApiKeyService


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_ADMIN_KEY = "env-admin-secret-001"


def _enable_auth(monkeypatch, tenant_enabled: bool = True):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RESOURCE_SCOPE_ENABLED", "true")
    monkeypatch.setenv("TENANT_ENABLED", "true" if tenant_enabled else "false")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", "admin")
    get_settings.cache_clear()


def _create_key(db_session, role="legal", tenants=None, groups=None):
    result = ApiKeyService(db_session).create_api_key(
        name=f"{role}-tenant-scoped",
        role=role,
        expires_at=None,
        created_by="test",
        allowed_group_ids=groups or [],
        allowed_case_ids=[],
        allowed_tenant_ids=tenants or [],
    )
    db_session.commit()
    return result["api_key"]


def _tenant(db_session, tenant_id: str, status: str = "active"):
    tenant = Tenant(tenant_id=tenant_id, tenant_name=f"{tenant_id}客户", status=status)
    db_session.add(tenant)
    db_session.commit()
    return tenant


def _case(db_session, case_no: str, group_id: str, tenant_id: str | None):
    legal_case = LegalCase(
        case_no=case_no,
        debtor_name="张三",
        tenant_id=tenant_id,
        group_id=group_id,
        due_date=date(2026, 6, 30),
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        status="normal",
    )
    db_session.add(legal_case)
    db_session.commit()
    return legal_case


def test_admin_can_create_tenant(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.post(
        "/api/v1/legal/tenants",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"tenant_id": "tenant_001", "tenant_name": "三叶草法务"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["tenant_id"] == "tenant_001"


def test_auditor_can_query_tenant(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    auditor_key = _create_key(db_session, "auditor")

    response = client.get("/api/v1/legal/tenants", headers={"X-API-Key": auditor_key})

    assert response.status_code == 200
    assert response.json()["data"]["total"] == 1


def test_legal_cannot_create_tenant(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    legal_key = _create_key(db_session, "legal")

    response = client.post(
        "/api/v1/legal/tenants",
        headers={"X-API-Key": legal_key},
        json={"tenant_id": "tenant_001", "tenant_name": "三叶草法务"},
    )

    assert response.status_code == 403


def test_create_case_accepts_tenant_id(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")

    response = client.post(
        "/api/v1/legal/cases",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={
            "tenant_id": "tenant_001",
            "case_no": "(2026)黔0281民初8001号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["tenant_id"] == "tenant_001"


def test_allowed_tenant_ids_filter_cases(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    _tenant(db_session, "tenant_002")
    _case(db_session, "(2026)黔0281民初8002号", "group_001", "tenant_001")
    _case(db_session, "(2026)黔0281民初8003号", "group_002", "tenant_002")
    key = _create_key(db_session, "legal", tenants=["tenant_001"])

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["tenant_id"] == "tenant_001"


def test_tenant_scope_and_group_scope_must_both_match(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    _case(db_session, "(2026)黔0281民初8004号", "group_001", "tenant_001")
    _case(db_session, "(2026)黔0281民初8005号", "group_002", "tenant_001")
    key = _create_key(db_session, "legal", tenants=["tenant_001"], groups=["group_001"])

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["group_id"] == "group_001"


def test_case_detail_outside_tenant_scope_returns_403(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    _tenant(db_session, "tenant_002")
    outside_case = _case(db_session, "(2026)黔0281民初8006号", "group_002", "tenant_002")
    key = _create_key(db_session, "legal", tenants=["tenant_001"])

    response = client.get(f"/api/v1/legal/cases/{outside_case.id}", headers={"X-API-Key": key})

    assert response.status_code == 403


def test_mock_message_with_tenant_id_writes_message_and_event_tenant(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    _case(db_session, "(2026)黔0281民初8007号", "group_001", "tenant_001")
    key = _create_key(db_session, "system", tenants=["tenant_001"], groups=["group_001"])

    response = client.post(
        "/api/v1/legal/messages/mock",
        headers={"X-API-Key": key},
        json={
            "tenant_id": "tenant_001",
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "案件(2026)黔0281民初8007号需要缴费400元",
        },
    )

    assert response.status_code == 200
    group_message = db_session.scalar(select(GroupMessage).where(GroupMessage.group_id == "group_001"))
    event = db_session.scalar(select(LegalEvent).where(LegalEvent.group_message_id == group_message.id))
    assert group_message.tenant_id == "tenant_001"
    assert event.tenant_id == "tenant_001"


def test_document_sync_logs_write_tenant_id(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    legal_case = _case(db_session, "(2026)黔0281民初8008号", "group_001", "tenant_001")

    response = client.post(f"/api/v1/legal/cases/{legal_case.id}/sync", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200
    sync_log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.case_id == legal_case.id))
    assert sync_log.tenant_id == "tenant_001"


def test_operation_audit_log_resource_scope_contains_allowed_tenants(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001")
    _case(db_session, "(2026)黔0281民初8009号", "group_001", "tenant_001")
    key = _create_key(db_session, "legal", tenants=["tenant_001"])

    response = client.get("/api/v1/legal/cases?tenant_id=tenant_001", headers={"X-API-Key": key})

    assert response.status_code == 200
    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/cases"))
    scope = json.loads(audit_log.resource_scope_json)
    assert scope["allowed_tenant_ids"]["items"] == ["tenant_001"]
    assert audit_log.tenant_id == "tenant_001"
    assert key not in (audit_log.resource_scope_json or "")


def test_tenant_enabled_false_skips_tenant_filter_but_keeps_group_scope(client, db_session, monkeypatch):
    _enable_auth(monkeypatch, tenant_enabled=False)
    _tenant(db_session, "tenant_001")
    _tenant(db_session, "tenant_002")
    _case(db_session, "(2026)黔0281民初8010号", "group_001", "tenant_001")
    _case(db_session, "(2026)黔0281民初8011号", "group_001", "tenant_002")
    _case(db_session, "(2026)黔0281民初8012号", "group_002", "tenant_002")
    key = _create_key(db_session, "legal", tenants=["tenant_001"], groups=["group_001"])

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert {item["tenant_id"] for item in items} == {"tenant_001", "tenant_002"}
    assert {item["group_id"] for item in items} == {"group_001"}


def test_disabled_tenant_blocks_non_admin_data_access(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session, "tenant_001", status="disabled")
    legal_case = _case(db_session, "(2026)黔0281民初8013号", "group_001", "tenant_001")
    key = _create_key(db_session, "legal", tenants=["tenant_001"])

    denied = client.get(f"/api/v1/legal/cases/{legal_case.id}", headers={"X-API-Key": key})
    admin_allowed = client.get(f"/api/v1/legal/cases/{legal_case.id}", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert denied.status_code == 403
    assert admin_allowed.status_code == 200


def test_sixth_migration_file_exists():
    assert (PROJECT_ROOT / "alembic" / "versions" / "0006_add_tenants_and_tenant_scopes.py").exists()
