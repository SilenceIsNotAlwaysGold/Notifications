import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config
from app.models.operation_audit_log import OperationAuditLog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADMIN_KEY = "dev-secret-key-001"


def _enable_auth(monkeypatch, keys: str = ADMIN_KEY):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", keys)
    monkeypatch.setenv("PUBLIC_ENDPOINTS", "/api/v1/health,/api/v1/health/detail")
    get_settings.cache_clear()


def _disable_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_KEYS", "")
    get_settings.cache_clear()


def test_auth_disabled_allows_legal_api_without_key(client, monkeypatch):
    _disable_auth(monkeypatch)

    response = client.get("/api/v1/legal/cases")

    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_auth_enabled_without_api_key_returns_401(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.get("/api/v1/legal/cases")

    assert response.status_code == 401
    assert response.json()["message"] == "未提供 API Key"


def test_auth_enabled_with_wrong_api_key_returns_401(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401
    assert response.json()["message"] == "API Key 无效或已过期"


def test_auth_enabled_with_valid_api_key_allows_legal_api(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": ADMIN_KEY, "X-Operator": "legal-admin"})

    assert response.status_code == 200
    assert response.json()["code"] == 0


def test_health_endpoints_are_public_when_auth_enabled(client, monkeypatch):
    _enable_auth(monkeypatch)

    basic = client.get("/api/v1/health")
    detail = client.get("/api/v1/health/detail")

    assert basic.status_code == 200
    assert detail.status_code == 200


def test_management_operation_writes_operation_audit_log(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": ADMIN_KEY, "X-Operator": "legal-admin"})

    assert response.status_code == 200
    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/cases"))
    assert audit_log is not None
    assert audit_log.operator == "legal-admin"
    assert audit_log.auth_type == "api_key"
    assert audit_log.status_code == 200


def test_audit_log_does_not_record_raw_api_key(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.post(
        "/api/v1/legal/messages/mock",
        headers={"X-API-Key": ADMIN_KEY, "X-Operator": "legal-admin"},
        json={
            "group_id": "group_001",
            "sender_id": "user_001",
            "msg_type": "text",
            "content": "无案号消息",
            "api_key": ADMIN_KEY,
            "token": "SECRET_TOKEN_VALUE",
        },
    )

    assert response.status_code == 200
    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/messages/mock"))
    assert audit_log is not None
    serialized = (audit_log.request_summary_json or "") + (audit_log.response_summary_json or "")
    assert ADMIN_KEY not in serialized
    assert "SECRET_TOKEN_VALUE" not in serialized


def test_operation_audit_logs_api_can_query(client, monkeypatch):
    _enable_auth(monkeypatch)
    headers = {"X-API-Key": ADMIN_KEY, "X-Operator": "legal-admin"}
    client.get("/api/v1/legal/cases", headers=headers)

    response = client.get("/api/v1/legal/operation-audit-logs", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] >= 1


def test_health_detail_only_exposes_admin_key_count(client, monkeypatch):
    _enable_auth(monkeypatch, keys=f"{ADMIN_KEY},another-secret-key-002")

    response = client.get("/api/v1/health/detail")

    assert response.status_code == 200
    body_text = response.text
    assert body_text.find(ADMIN_KEY) == -1
    body = response.json()
    assert body["auth"]["enabled"] is True
    assert body["auth"]["admin_key_count"] == 2


def test_config_validator_auth_enabled_without_keys_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert any("ADMIN_API_KEYS" in message for message in result["errors"])
    get_settings.cache_clear()


def test_second_migration_file_exists():
    assert (PROJECT_ROOT / "alembic" / "versions" / "0002_add_operation_audit_logs.py").exists()


def test_audit_request_summary_masks_sensitive_json_values(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)

    client.post(
        "/api/v1/legal/messages/mock",
        headers={"X-API-Key": ADMIN_KEY},
        json={
            "group_id": "group_002",
            "sender_id": "user_002",
            "msg_type": "text",
            "content": "现场开庭",
            "secret": "DO_NOT_STORE",
            "private_key": "PRIVATE_KEY_VALUE",
        },
    )

    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/messages/mock"))
    summary = json.loads(audit_log.request_summary_json)
    assert summary["json"]["secret"] == "***"
    assert summary["json"]["private_key"] == "***"
