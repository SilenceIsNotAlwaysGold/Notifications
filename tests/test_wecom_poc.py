from pathlib import Path

import httpx

from app.core.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_ADMIN_KEY = "env-admin-secret-001"


def _enable_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", "admin")
    get_settings.cache_clear()


def test_send_test_empty_webhook_url_returns_error(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.post(
        "/api/v1/legal/wecom-poc/send-test",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"webhook_url": "", "content": "企业微信机器人发送测试"},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "webhook_url 不能为空"


def test_send_test_does_not_leak_webhook_key(client, monkeypatch):
    _enable_auth(monkeypatch)
    secret_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-key-001"

    def fake_post(url, json=None, timeout=None):
        assert url == secret_url
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr("app.api.v1.wecom_poc.httpx.post", fake_post)

    response = client.post(
        "/api/v1/legal/wecom-poc/send-test",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"webhook_url": secret_url, "content": "企业微信机器人发送测试"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["success"] is True
    assert data["errcode"] == 0
    assert data["errmsg"] == "ok"
    assert "secret-key-001" not in response.text


def test_archive_check_missing_corp_id_returns_missing_fields(client, monkeypatch):
    _enable_auth(monkeypatch)

    response = client.post(
        "/api/v1/legal/wecom-poc/archive-check",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={"archive_secret": "secret", "private_key_path": "/secure/private.pem", "public_key_ver": "1"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready"] is False
    assert "corp_id" in data["missing_fields"]
    assert "sidecar_url" in data["missing_fields"]


def test_archive_check_private_key_or_path_is_enough(client, monkeypatch):
    _enable_auth(monkeypatch)

    with_key = client.post(
        "/api/v1/legal/wecom-poc/archive-check",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "private_key": "PRIVATE",
            "public_key_ver": "1",
            "sidecar_url": "http://127.0.0.1:9001/wecom-archive",
        },
    )
    with_path = client.post(
        "/api/v1/legal/wecom-poc/archive-check",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "private_key_path": "/secure/private.pem",
            "public_key_ver": "1",
            "sidecar_url": "http://127.0.0.1:9001/wecom-archive",
        },
    )

    assert with_key.json()["data"]["ready"] is True
    assert with_path.json()["data"]["ready"] is True


def test_archive_check_does_not_return_private_key_plaintext(client, monkeypatch):
    _enable_auth(monkeypatch)
    private_key = "-----BEGIN PRIVATE KEY-----secret-private-key-----END PRIVATE KEY-----"

    response = client.post(
        "/api/v1/legal/wecom-poc/archive-check",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json={
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "private_key": private_key,
            "public_key_ver": "1",
            "sidecar_url": "http://127.0.0.1:9001/wecom-archive",
        },
    )

    assert response.status_code == 200
    assert private_key not in response.text
    assert "secret-private-key" not in response.text


def test_current_archive_check_reads_environment_without_leaking_secret(client, monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setenv("WECOM_CORP_ID", "wwee945c1253a61052")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "archive-secret-value")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    get_settings.cache_clear()

    response = client.get("/api/v1/legal/wecom-poc/archive-check/current", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready"] is True
    assert data["missing_fields"] == []
    assert "archive-secret-value" not in response.text


def test_current_archive_check_reports_missing_secret_and_public_key(client, monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setenv("WECOM_CORP_ID", "wwee945c1253a61052")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "")
    get_settings.cache_clear()

    response = client.get("/api/v1/legal/wecom-poc/archive-check/current", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ready"] is False
    assert data["missing_fields"] == ["archive_secret", "public_key_ver", "sidecar_url"]


def test_wecom_feasibility_docs_exist():
    assert (PROJECT_ROOT / "docs" / "wecom_integration_feasibility.md").exists()
    assert (PROJECT_ROOT / "docs" / "wecom_customer_checklist.md").exists()
