import os
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _messages(result):
    return "\n".join(result["errors"] + result["warnings"])


def test_webhook_mode_without_webhook_url_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "webhook")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "WECOM_WEBHOOK_URL" in _messages(result)
    get_settings.cache_clear()


def test_wecomapi_mode_without_dedicated_account_config_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "")
    monkeypatch.setenv("WECOMAPI_TOKEN", "")
    monkeypatch.setenv("WECOMAPI_GUID", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "WECOMAPI_BASE_URL" in _messages(result)
    assert "WECOMAPI_TOKEN" in _messages(result)
    assert "WECOMAPI_GUID" in _messages(result)
    get_settings.cache_clear()


def test_wecomapi_mode_with_https_config_returns_risk_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("WECOMAPI_TOKEN", "test-token")
    monkeypatch.setenv("WECOMAPI_GUID", "test-guid")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    item = next(item for item in result["items"] if item["name"] == "WECOM_SEND_MODE")
    assert item["status"] == "warning"
    assert "非官方兼容网关" in item["message"]
    assert "Android RPA" in item["message"]
    get_settings.cache_clear()


def test_wecom_cli_mode_without_binary_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_cli")
    monkeypatch.setenv("WECOM_CLI_BINARY", "missing-wecom-cli")
    monkeypatch.setenv("WECOM_CLI_CONFIG_DIR", str(tmp_path / "wecom"))
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    monkeypatch.setattr("app.core.config_validator.shutil.which", lambda _: None)
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "@wecom/cli" in _messages(result)
    get_settings.cache_clear()


def test_wecom_cli_mode_requires_initialization(monkeypatch, tmp_path):
    config_dir = tmp_path / "wecom"
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_cli")
    monkeypatch.setenv("WECOM_CLI_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    monkeypatch.setattr("app.core.config_validator.shutil.which", lambda _: "/usr/local/bin/wecom-cli")
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "wecom-cli init" in _messages(result)
    get_settings.cache_clear()


def test_wecom_cli_mode_initialized_returns_permission_warning(monkeypatch, tmp_path):
    config_dir = tmp_path / "wecom"
    config_dir.mkdir()
    (config_dir / "bot.enc").write_text("encrypted", encoding="utf-8")
    (config_dir / "mcp_config.enc").write_text("encrypted", encoding="utf-8")
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_cli")
    monkeypatch.setenv("WECOM_CLI_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    monkeypatch.setattr("app.core.config_validator.shutil.which", lambda _: "/usr/local/bin/wecom-cli")
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    item = next(item for item in result["items"] if item["name"] == "WECOM_SEND_MODE")
    assert item["status"] == "warning"
    assert "wecom-cli msg --help" in item["message"]
    get_settings.cache_clear()


def test_wecom_bot_mode_requires_sidecar_config(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_bot")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_URL", "")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_TOKEN", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "WECOM_BOT_SIDECAR_URL" in _messages(result)
    assert "WECOM_BOT_SIDECAR_TOKEN" in _messages(result)
    get_settings.cache_clear()


def test_wecom_bot_mode_with_local_sidecar_is_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecom_bot")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_URL", "http://127.0.0.1:8788")
    monkeypatch.setenv("WECOM_BOT_SIDECAR_TOKEN", "test-sidecar-token-123456")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    item = next(item for item in result["items"] if item["name"] == "WECOM_SEND_MODE")
    assert item["status"] == "ok"
    assert "官方智能机器人 WebSocket sidecar" in item["message"]
    get_settings.cache_clear()


def test_tencent_doc_real_without_token_or_sheet_id_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TENCENT_DOC_MODE", "real")
    monkeypatch.setenv("TENCENT_DOC_ACCESS_TOKEN", "")
    monkeypatch.setenv("TENCENT_DOC_SHEET_ID", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "TENCENT_DOC_ACCESS_TOKEN" in _messages(result)
    assert "TENCENT_DOC_SHEET_ID" in _messages(result)
    get_settings.cache_clear()


def test_kdocs_mcp_real_requires_core_target_files(monkeypatch, tmp_path):
    monkeypatch.setenv("KDOCS_MODE", "real")
    monkeypatch.setenv("KDOCS_TRANSPORT", "mcp")
    monkeypatch.setenv("KDOCS_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("KDOCS_MCP_URL", "https://mcp.kdocs.test")
    monkeypatch.setenv("KDOCS_MCP_CLIENT_ID", "client-001")
    monkeypatch.setenv("KDOCS_DRIVE_ID", "drive-001")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_FILE_ID", "")
    monkeypatch.setenv("KDOCS_COURT_TIME_FILE_ID", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "KDOCS_ENFORCEMENT_FILE_ID" in _messages(result)
    assert "KDOCS_COURT_TIME_FILE_ID" in _messages(result)
    get_settings.cache_clear()


def test_kdocs_mcp_real_requires_payment_target(monkeypatch, tmp_path):
    monkeypatch.setenv("KDOCS_MODE", "real")
    monkeypatch.setenv("KDOCS_TRANSPORT", "mcp")
    monkeypatch.setenv("KDOCS_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("KDOCS_MCP_URL", "https://mcp.kdocs.test")
    monkeypatch.setenv("KDOCS_MCP_CLIENT_ID", "client-001")
    monkeypatch.setenv("KDOCS_DRIVE_ID", "drive-001")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_FILE_ID", "enforcement-file")
    monkeypatch.setenv("KDOCS_COURT_TIME_FILE_ID", "court-file")
    monkeypatch.setenv("KDOCS_PAYMENT_FILE_ID", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    kdocs_item = next(item for item in result["items"] if item["name"] == "KDOCS_MODE")
    assert kdocs_item["status"] == "error"
    assert "KDOCS_PAYMENT_FILE_ID" in kdocs_item["message"]
    get_settings.cache_clear()


def test_wecom_archive_real_without_sidecar_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "WECOM_ARCHIVE_SIDECAR_URL" in _messages(result)
    get_settings.cache_clear()


def test_wecom_archive_real_with_sidecar_returns_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert not any(item["name"] == "WECOM_ARCHIVE_MODE" and item["status"] == "error" for item in result["items"])
    get_settings.cache_clear()


def test_wecom_archive_real_sidecar_mock_allows_missing_credentials_with_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "real")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_MOCK", "true")
    monkeypatch.setenv("WECOM_CORP_ID", "")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is True
    assert any(item["name"] == "WECOM_ARCHIVE_MODE" and item["status"] == "warning" for item in result["items"])
    assert "sidecar mock" in _messages(result)
    get_settings.cache_clear()


def test_media_download_real_without_sidecar_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DOWNLOAD_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "MEDIA_DOWNLOAD_MODE=real" in _messages(result)
    assert "WECOM_ARCHIVE_SIDECAR_URL" in _messages(result)
    get_settings.cache_clear()


def test_media_download_real_with_sidecar_returns_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DOWNLOAD_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert not any(item["name"] == "MEDIA_DOWNLOAD_MODE" and item["status"] == "error" for item in result["items"])
    get_settings.cache_clear()


def test_media_download_real_sidecar_mock_allows_missing_credentials_with_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DOWNLOAD_MODE", "real")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_MOCK", "true")
    monkeypatch.setenv("WECOM_CORP_ID", "")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is True
    assert any(item["name"] == "MEDIA_DOWNLOAD_MODE" and item["status"] == "warning" for item in result["items"])
    assert "sidecar mock" in _messages(result)
    get_settings.cache_clear()


def test_local_text_ocr_provider_returns_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_PROVIDER", "local_text")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert any(item["name"] == "OCR_PROVIDER" and item["status"] == "warning" for item in result["items"])
    get_settings.cache_clear()


def test_tencent_ocr_without_sidecar_returns_config_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_PROVIDER", "tencent")
    monkeypatch.setenv("OCR_SIDECAR_URL", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert result["ok"] is False
    assert "OCR_SIDECAR_URL" in _messages(result)
    get_settings.cache_clear()


def test_aliyun_ocr_with_sidecar_returns_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_PROVIDER", "aliyun")
    monkeypatch.setenv("OCR_SIDECAR_URL", "http://127.0.0.1:9002")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert not any(item["name"] == "OCR_PROVIDER" and item["status"] == "error" for item in result["items"])
    get_settings.cache_clear()


def test_llm_extraction_without_gateway_config_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    item = next(item for item in result["items"] if item["name"] == "LEGAL_EXTRACTION_MODE")
    assert item["status"] == "error"
    assert "LEGAL_LLM_BASE_URL" in item["message"]
    get_settings.cache_clear()


def test_llm_extraction_with_authenticated_gateway_returns_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LEGAL_LLM_API_KEY", "test-key")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "legal-extractor-test")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    item = next(item for item in result["items"] if item["name"] == "LEGAL_EXTRACTION_MODE")
    assert item["status"] == "ok"
    assert "LLM" in item["message"]
    get_settings.cache_clear()


def test_db_auto_create_true_returns_warning(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_AUTO_CREATE", "true")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    get_settings.cache_clear()

    result = validate_runtime_config(get_settings())

    assert any(item["name"] == "DB_AUTO_CREATE" and item["status"] == "warning" for item in result["items"])
    get_settings.cache_clear()


def test_health_returns_basic_ok(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "legal-wecom-automation"
    assert body["env"] == "test"
    assert "time" in body


def test_health_detail_returns_runtime_sections(client):
    response = client.get("/api/v1/health/detail")

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"status", "database", "config", "storage", "scheduler", "sender"}
    assert body["database"]["status"] == "ok"
    assert "running" in body["scheduler"]
    assert "jobs" in body["scheduler"]
    assert "writable" in body["storage"]
    assert "errors" in body["config"]
    assert "warnings" in body["config"]
    assert body["sender"]["status"] == "disabled"


def test_health_detail_reports_sanitized_android_sender_status(client, monkeypatch):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "http://sender.internal:8092")
    monkeypatch.setenv("WECOMAPI_TOKEN", "SECRET_SENDER_TOKEN")
    monkeypatch.setenv("WECOMAPI_GUID", "SECRET_SENDER_DEVICE_ID")
    monkeypatch.setattr(
        "app.api.v1.health.WeComSenderStatusClient.check",
        lambda self: {
            "status": "ok",
            "message": "Android 发送设备在线",
            "backend": "android",
            "configured": True,
            "online": True,
            "connected_at": "2026-07-21T09:00:00+00:00",
            "pending_commands": 0,
            "target_count": 2,
            "status_code": 200,
        },
    )
    get_settings.cache_clear()

    response = client.get("/api/v1/health/detail")

    body = response.json()
    assert body["sender"]["status"] == "ok"
    assert body["sender"]["online"] is True
    assert body["sender"]["target_count"] == 2
    assert "SECRET_SENDER_TOKEN" not in response.text
    assert "SECRET_SENDER_DEVICE_ID" not in response.text
    assert "sender.internal" not in response.text
    get_settings.cache_clear()


def test_admin_console_static_files_available(client):
    redirect_response = client.get("/admin", follow_redirects=False)
    assert redirect_response.status_code in {307, 308}
    assert redirect_response.headers["location"] == "/admin/"

    index_response = client.get("/admin/")
    assert index_response.status_code == 200
    assert "法务群自动化管理后台" in index_response.text
    assert "/admin/admin.js" in index_response.text

    js_response = client.get("/admin/admin.js")
    assert js_response.status_code == 200
    assert "legal_wecom_api_key" in js_response.text
    assert "legal_wecom_view" in js_response.text
    assert "window.location.hash" in js_response.text
    assert 'window.addEventListener("popstate"' in js_response.text
    assert "Android 发送端" in js_response.text
    assert "发送账号登录" in js_response.text
    assert "手机号或验证码" in js_response.text
    assert "data-device-key=\"home\"" not in js_response.text
    assert "/api/v1/legal/android-device/screenshot" in js_response.text

    css_response = client.get("/admin/styles.css")
    assert css_response.status_code == 200
    assert "position: sticky" in css_response.text
    assert "height: 100vh" in css_response.text
    assert "overflow-y: auto" in css_response.text


def test_health_detail_does_not_expose_sensitive_values(client, monkeypatch):
    monkeypatch.setenv("WECOM_SEND_MODE", "webhook")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRET_WEBHOOK_KEY")
    monkeypatch.setenv("WECOMAPI_TOKEN", "SECRET_WECOMAPI_TOKEN")
    monkeypatch.setenv("TENCENT_DOC_MODE", "real")
    monkeypatch.setenv("TENCENT_DOC_ACCESS_TOKEN", "SECRET_DOC_TOKEN")
    monkeypatch.setenv("TENCENT_DOC_SHEET_ID", "SECRET_SHEET_ID")
    get_settings.cache_clear()

    response = client.get("/api/v1/health/detail")

    body_text = response.text
    assert "SECRET_WEBHOOK_KEY" not in body_text
    assert "SECRET_WECOMAPI_TOKEN" not in body_text
    assert "SECRET_DOC_TOKEN" not in body_text
    assert "SECRET_SHEET_ID" not in body_text
    get_settings.cache_clear()


def test_config_cli_returns_nonzero_for_error_config(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{tmp_path / 'cli.db'}",
            "DB_AUTO_CREATE": "false",
            "WECOM_SEND_MODE": "webhook",
            "WECOM_WEBHOOK_URL": "",
            "TENCENT_DOC_MODE": "mock",
            "WECOM_ARCHIVE_MODE": "mock",
            "OCR_PROVIDER": "mock",
            "MEDIA_STORAGE_DIR": str(tmp_path / "media"),
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "check-config"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "WECOM_WEBHOOK_URL" in result.stdout


def test_dockerfile_exists_and_uses_uvicorn():
    dockerfile = PROJECT_ROOT / "Dockerfile"

    assert dockerfile.exists()
    content = dockerfile.read_text(encoding="utf-8")
    assert "python:3.11-slim" in content
    assert "uvicorn" in content
    assert "app.main:app" in content


def test_dockerignore_excludes_runtime_and_secret_files():
    dockerignore = PROJECT_ROOT / ".dockerignore"

    assert dockerignore.exists()
    content = dockerignore.read_text(encoding="utf-8")
    for pattern in [".env", "*.pem", "*.key", "*.db", "storage/", "test_storage/", "wxarchive/"]:
        assert pattern in content


def test_release_check_script_covers_core_delivery_checks():
    script = PROJECT_ROOT / "scripts" / "release_check.sh"

    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "pytest -q" in content
    assert "alembic upgrade head" in content
    assert "python3 -m app.cli check-config" in content
    assert "acceptance_ocr_samples.py" in content
    assert "LIVE_BASE_URL" in content
    assert "docker compose config" in content
    assert "scripts/backup.py" in content
    assert "scripts/restore.py" in content


def test_production_compose_contains_internal_sidecars_and_operations_tasks():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    for service in ["api:", "ocr-sidecar:", "archive-sidecar:", "wecom-bot:", "migrate:", "backup:"]:
        assert service in compose
    assert compose.count("ports:") == 1
    assert 'profiles: ["robot"]' in compose
    assert 'profiles: ["operations"]' in compose
    assert "service_completed_successfully" in compose
    assert "service_healthy" in compose


def test_backup_restore_and_systemd_delivery_files_exist():
    for relative_path in [
        "scripts/backup.py",
        "scripts/restore.py",
        "deploy/legal-wecom-backup.service",
        "deploy/legal-wecom-backup.timer",
        "docs/operations.md",
        "wecom_bot_sidecar/Dockerfile",
    ]:
        assert (PROJECT_ROOT / relative_path).exists()

    timer = (PROJECT_ROOT / "deploy/legal-wecom-backup.timer").read_text(encoding="utf-8")
    service = (PROJECT_ROOT / "deploy/legal-wecom-backup.service").read_text(encoding="utf-8")
    assert "OnCalendar=" in timer
    assert "docker compose --profile operations run --rm backup" in service


def test_github_actions_ci_runs_pytest_and_alembic():
    ci_file = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

    assert ci_file.exists()
    content = ci_file.read_text(encoding="utf-8")
    assert "pytest -q" in content
    assert "alembic upgrade head" in content
