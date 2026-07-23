import json

import httpx

from app.core.config import get_settings
from app.schemas.recognition_settings import RecognitionSettingsUpdate
from app.services.recognition_settings_service import RecognitionSettingsService


def test_recognition_settings_api_masks_all_secrets(client, monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "tencent")
    monkeypatch.setenv("TENCENT_OCR_SECRET_ID", "SECRET_TENCENT_ID")
    monkeypatch.setenv("TENCENT_OCR_SECRET_KEY", "SECRET_TENCENT_KEY")
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LEGAL_LLM_API_KEY", "SECRET_LLM_KEY")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "deepseek-chat")
    get_settings.cache_clear()

    response = client.get("/api/v1/legal/recognition-settings")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["has_tencent_secret_id"] is True
    assert data["has_tencent_secret_key"] is True
    assert data["has_llm_api_key"] is True
    assert data["llm_model"] == "deepseek-chat"
    assert "SECRET_TENCENT" not in response.text
    assert "SECRET_LLM_KEY" not in response.text


def test_recognition_settings_update_writes_whitelisted_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=production\nLEGAL_EXTRACTION_MODE=regex\n", encoding="utf-8")
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "regex")
    get_settings.cache_clear()

    service = RecognitionSettingsService(get_settings(), env_file=env_file)
    service.update(
        RecognitionSettingsUpdate(
            ocr_provider="tencent",
            extraction_mode="llm",
            llm_base_url="https://api.deepseek.com/v1",
            llm_api_key="new-secret-key",
            llm_model="deepseek-chat",
            llm_min_confidence=0.8,
            llm_fallback_to_regex=True,
        )
    )

    written = env_file.read_text(encoding="utf-8")
    assert "APP_ENV=production" in written
    assert "OCR_PROVIDER=tencent" in written
    assert "LEGAL_EXTRACTION_MODE=llm" in written
    assert "LEGAL_LLM_BASE_URL=https://api.deepseek.com/v1" in written
    assert "LEGAL_LLM_API_KEY=new-secret-key" in written
    assert "LEGAL_LLM_MODEL=deepseek-chat" in written
    assert "LEGAL_LLM_MIN_CONFIDENCE=0.8" in written
    assert list(tmp_path.glob(".env.bak.*"))


def test_recognition_check_reports_ocr_and_llm_available(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "tencent")
    monkeypatch.setenv("OCR_SIDECAR_URL", "http://127.0.0.1:9002")
    monkeypatch.setenv("TENCENT_OCR_SECRET_ID", "secret-id")
    monkeypatch.setenv("TENCENT_OCR_SECRET_KEY", "secret-key")
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LEGAL_LLM_API_KEY", "llm-secret")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "deepseek-chat")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.services.recognition_settings_service.httpx.get",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"status": "ok", "configured": True},
            request=httpx.Request("GET", "http://127.0.0.1:9002/health"),
        ),
    )

    def fake_post(url, headers, json, timeout):
        assert url == "https://api.deepseek.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer llm-secret"
        assert json["model"] == "deepseek-chat"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.recognition_settings_service.httpx.post", fake_post)

    status = RecognitionSettingsService(get_settings()).check()

    assert status.ocr.available is True
    assert status.llm.available is True


def test_recognition_settings_audit_masks_keys(client, db_session, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("app.services.recognition_settings_service.DEFAULT_ENV_FILE", env_file)

    response = client.put(
        "/api/v1/legal/recognition-settings",
        json={"llm_api_key": "SECRET_MODEL_KEY"},
    )

    assert response.status_code == 200
    assert "SECRET_MODEL_KEY" not in response.text
    from sqlalchemy import select

    from app.models.operation_audit_log import OperationAuditLog

    audit_log = db_session.scalar(
        select(OperationAuditLog).where(OperationAuditLog.path == "/api/v1/legal/recognition-settings")
    )
    assert audit_log is not None
    summary = json.loads(audit_log.request_summary_json)
    assert summary["json"]["llm_api_key"] == "***"
