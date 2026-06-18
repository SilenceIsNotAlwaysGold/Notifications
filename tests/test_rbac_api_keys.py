from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config
from app.models.api_key import ApiKey
from app.models.operation_audit_log import OperationAuditLog
from app.services.api_key_service import ApiKeyService
from app.utils.datetime_utils import now_tz


ENV_ADMIN_KEY = "env-admin-secret-001"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _enable_auth(monkeypatch, default_role="admin"):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", default_role)
    get_settings.cache_clear()


def _create_db_key(db_session, role: str, name: str | None = None, expires_at=None) -> str:
    result = ApiKeyService(db_session).create_api_key(name=name or f"{role}-key", role=role, expires_at=expires_at, created_by="test")
    db_session.commit()
    return result["api_key"]


def test_admin_key_can_access_management_api(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.get("/api/v1/legal/operation-audit-logs", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200


def test_legal_role_can_get_cases(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "legal")

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_legal_role_cannot_access_operation_audit_logs(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "legal")

    response = client.get("/api/v1/legal/operation-audit-logs", headers={"X-API-Key": key})

    assert response.status_code == 403
    assert response.json()["message"] == "无权限访问该接口"


def test_auditor_role_can_get_operation_audit_logs(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "auditor")

    response = client.get("/api/v1/legal/operation-audit-logs", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_auditor_role_cannot_create_case(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "auditor")

    response = client.post(
        "/api/v1/legal/cases",
        headers={"X-API-Key": key},
        json={
            "case_no": "(2026)黔0281民初9901号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )

    assert response.status_code == 403


def test_system_role_can_run_due(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "system")

    response = client.post("/api/v1/legal/reminders/run-due", headers={"X-API-Key": key})

    assert response.status_code == 200


def test_system_role_cannot_get_operation_audit_logs(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "system")

    response = client.get("/api/v1/legal/operation-audit-logs", headers={"X-API-Key": key})

    assert response.status_code == 403


def test_replay_endpoint_only_admin_can_call(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    legal_key = _create_db_key(db_session, "legal")
    admin_key = _create_db_key(db_session, "admin")
    payload = {"messages": []}

    denied = client.post("/api/v1/legal/wecom-archive/replay", headers={"X-API-Key": legal_key}, json=payload)
    allowed = client.post("/api/v1/legal/wecom-archive/replay", headers={"X-API-Key": admin_key}, json=payload)

    assert denied.status_code == 403
    assert allowed.status_code == 200


def test_create_api_key_returns_plaintext_once_and_list_hides_secret(client, monkeypatch):
    _enable_auth(monkeypatch)
    headers = {"X-API-Key": ENV_ADMIN_KEY, "X-Operator": "admin"}

    created = client.post(
        "/api/v1/legal/api-keys",
        headers=headers,
        json={"name": "法务操作员", "role": "legal"},
    )

    assert created.status_code == 200
    created_data = created.json()["data"]
    assert created_data["api_key"].startswith("lwk_live_")
    listed = client.get("/api/v1/legal/api-keys", headers=headers)
    listed_text = listed.text
    assert created_data["api_key"] not in listed_text
    assert "key_hash" not in listed_text


def test_revoke_api_key_makes_it_unusable(client, monkeypatch):
    _enable_auth(monkeypatch)
    headers = {"X-API-Key": ENV_ADMIN_KEY, "X-Operator": "admin"}
    created = client.post("/api/v1/legal/api-keys", headers=headers, json={"name": "临时 key", "role": "legal"})
    data = created.json()["data"]

    revoke = client.post(f"/api/v1/legal/api-keys/{data['id']}/revoke", headers=headers)
    after = client.get("/api/v1/legal/cases", headers={"X-API-Key": data["api_key"]})

    assert revoke.status_code == 200
    assert after.status_code == 401


def test_expired_key_is_rejected(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "legal", expires_at=now_tz() - timedelta(days=1))

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key})

    assert response.status_code == 401


def test_env_admin_keys_remain_compatible_with_default_role(client, monkeypatch):
    _enable_auth(monkeypatch, default_role="auditor")

    get_cases = client.get("/api/v1/legal/cases", headers={"X-API-Key": ENV_ADMIN_KEY})
    post_case = client.post(
        "/api/v1/legal/cases",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={
            "case_no": "(2026)黔0281民初9902号",
            "debtor_name": "张三",
            "group_id": "group_001",
            "due_date": "2026-06-30",
            "total_amount": "1000.00",
        },
    )

    assert get_cases.status_code == 200
    assert post_case.status_code == 403


def test_audit_log_records_role_and_prefix_without_plaintext_key(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    key = _create_db_key(db_session, "legal", name="legal-user")

    response = client.get("/api/v1/legal/cases", headers={"X-API-Key": key, "X-Operator": "legal-user"})

    assert response.status_code == 200
    audit_log = db_session.scalar(select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/cases"))
    assert audit_log.operator_role == "legal"
    assert audit_log.api_key_prefix == key[:6]
    assert key not in (audit_log.request_summary_json or "")


def test_api_key_is_not_stored_in_plaintext(db_session):
    raw_key = _create_db_key(db_session, "legal")
    api_key = db_session.scalar(select(ApiKey).where(ApiKey.key_prefix == raw_key[:6]))

    assert api_key is not None
    assert api_key.key_hash != raw_key
    assert raw_key not in api_key.key_hash


def test_auth_validator_warns_for_env_admin_keys_and_invalid_default_role(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "false")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", "not-a-role")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert any("DEFAULT_API_KEY_ROLE" in message for message in result["errors"])
    assert any("RBAC_ENABLED=false" in message for message in result["warnings"])
    assert any("数据库 API Key" in message for message in result["warnings"])
    get_settings.cache_clear()


def test_third_and_fourth_migration_files_exist():
    versions = {path.name for path in (PROJECT_ROOT / "alembic" / "versions").iterdir()}
    assert "0003_add_api_keys.py" in versions
    assert "0004_add_audit_auth_fields.py" in versions
