from pathlib import Path

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config


ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_wecomapi(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WECOM_SEND_MODE", "mock")
    get_settings.cache_clear()
    result = validate_runtime_config(get_settings())
    assert any("mock 发送仅允许" in message for message in result["errors"])


def test_complete_wecomapi_config_is_accepted(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_TOKEN", "test-token")
    monkeypatch.setenv("WECOMAPI_GUID", "test-guid")
    get_settings.cache_clear()
    result = validate_runtime_config(get_settings())
    assert not any("WECOM_SEND_MODE=wecomapi 时缺少配置" in message for message in result["errors"])


def test_health_and_admin_are_available(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/detail").status_code == 200
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/admin.js").status_code == 200


def test_compose_contains_only_current_runtime_services():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ("api:", "ocr-sidecar:", "archive-sidecar:", "migrate:", "backup:"):
        assert service in compose
    for legacy in ("wecom-bot:", "wecom-android:", "wecom-sender:", "wecom-protocol-gateway:"):
        assert legacy not in compose
    assert compose.count("ports:") == 1
    assert 'profiles: ["operations"]' in compose


def test_release_and_recovery_artifacts_exist():
    for relative in (
        "Dockerfile",
        "scripts/release_check.sh",
        "scripts/backup.py",
        "scripts/restore.py",
        "scripts/migration_preflight.py",
        "deploy/legal-wecom-backup.service",
        "deploy/legal-wecom-backup.timer",
        "docs/operations-refactor.md",
    ):
        assert (ROOT / relative).exists()

    backup_service = (ROOT / "deploy/legal-wecom-backup.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/opt/legal-wecom-automation/.env" in backup_service
    assert ".venv/bin/python /opt/legal-wecom-automation/scripts/backup.py" in backup_service
    assert "docker compose" not in backup_service


def test_legacy_sender_implementations_are_removed():
    for relative in (
        "android_sender_client",
        "wecom_sender_sidecar",
        "wecom_native_lab",
        "wecom_protocol_gateway",
        "wecom_bot_sidecar",
        "Dockerfile.protocol-gateway",
        "docker-compose.android.yml",
    ):
        assert not (ROOT / relative).exists(), relative


def test_gitignore_and_dockerignore_protect_runtime_secrets():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert ".env" in dockerignore
    assert "*.db" in gitignore
