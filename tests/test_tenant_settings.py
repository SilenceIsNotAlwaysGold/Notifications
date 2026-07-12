import json
import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.legal_case import LegalCase
from app.models.reminder import Reminder
from app.models.tenant import Tenant
from app.models.tenant_setting import TenantSetting
from app.services.api_key_service import ApiKeyService
from app.services.case_lifecycle_service import CaseLifecycleService
from app.services.ocr_service import OCRService
from app.services.tenant_settings_service import TenantSettingsService
from app.utils.datetime_utils import now_tz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_ADMIN_KEY = "env-admin-secret-001"


def _enable_auth(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("RBAC_ENABLED", "true")
    monkeypatch.setenv("RESOURCE_SCOPE_ENABLED", "true")
    monkeypatch.setenv("TENANT_ENABLED", "true")
    monkeypatch.setenv("TENANT_SETTINGS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_API_KEYS", ENV_ADMIN_KEY)
    monkeypatch.setenv("DEFAULT_API_KEY_ROLE", "admin")
    get_settings.cache_clear()


def _tenant(db_session, tenant_id="tenant_001"):
    tenant = Tenant(tenant_id=tenant_id, tenant_name=f"{tenant_id}客户", status="active")
    db_session.add(tenant)
    db_session.commit()
    return tenant


def _case(db_session, tenant_id="tenant_001", group_id="group_001", due_date=None):
    legal_case = LegalCase(
        tenant_id=tenant_id,
        case_no=f"(2026)黔0281民初{8000 + len(list(db_session.scalars(select(LegalCase)).all()))}号",
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


def _create_key(db_session, role="auditor"):
    result = ApiKeyService(db_session).create_api_key(role=role, name=f"{role}-key", expires_at=None, created_by="test")
    db_session.commit()
    return result["api_key"]


def _put_settings(client, payload):
    return client.put(
        "/api/v1/legal/tenants/tenant_001/settings",
        headers={"X-API-Key": ENV_ADMIN_KEY},
        json=payload,
    )


def test_admin_can_create_or_update_tenant_settings(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)

    response = _put_settings(client, {"ocr_provider": "local_text", "repayment_reminder_days_before": 5})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ocr_provider"] == "local_text"
    assert data["repayment_reminder_days_before"] == 5
    assert db_session.scalar(select(TenantSetting).where(TenantSetting.tenant_id == "tenant_001")) is not None


def test_auditor_can_read_masked_tenant_settings(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"wecom_webhook_url": "https://example.com/webhook?key=secret", "tencent_doc_access_token": "token-secret"})
    auditor_key = _create_key(db_session, "auditor")

    response = client.get("/api/v1/legal/tenants/tenant_001/settings", headers={"X-API-Key": auditor_key})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["has_wecom_webhook_url"] is True
    assert data["wecom_webhook_url"] == "******"
    assert data["has_tencent_doc_access_token"] is True
    assert data["tencent_doc_access_token"] == "******"
    assert "secret" not in response.text


def test_legal_cannot_read_tenant_settings(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    legal_key = _create_key(db_session, "legal")

    response = client.get("/api/v1/legal/tenants/tenant_001/settings", headers={"X-API-Key": legal_key})

    assert response.status_code == 403


def test_effective_settings_inherit_global_when_missing(db_session):
    _tenant(db_session)

    effective = TenantSettingsService(db_session).get_effective_settings("tenant_001")

    assert effective["source"] == "global"
    assert effective["ocr"]["provider"] == get_settings().ocr_provider


def test_tenant_settings_override_ocr_provider_local_text(client, db_session, monkeypatch, tmp_path):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"ocr_provider": "local_text"})
    pdf_path = tmp_path / "a.pdf"
    txt_path = tmp_path / "a.txt"
    pdf_path.write_bytes(b"pdf")
    txt_path.write_text("案件(2026)黔0281民初3118号需要缴费400元", encoding="utf-8")

    result = OCRService().extract_from_file(str(pdf_path), "pdf", tenant_id="tenant_001")

    assert result["success"] is True
    assert result["provider"] == "local_text"
    assert result["event_type"] == "payment_notice"


def test_tenant_settings_override_repayment_reminder_days(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"repayment_reminder_days_before": 5})
    legal_case = _case(db_session, due_date=now_tz().date() + timedelta(days=5))

    result = CaseLifecycleService(db_session).scan_cases(today=now_tz().date())

    reminders = list(db_session.scalars(select(Reminder).where(Reminder.case_id == legal_case.id)).all())
    assert result["created_repayment_reminders"] == 1
    assert len(reminders) == 1


def test_wecom_send_disabled_by_feature_flag(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"feature_flags": {"enable_wecom_send": False}})
    reminder = Reminder(
        tenant_id="tenant_001",
        group_id="group_001",
        reminder_type="custom",
        remind_at=now_tz() - timedelta(minutes=1),
        content="请跟进",
        status="pending",
    )
    db_session.add(reminder)
    db_session.commit()

    result = client.post("/api/v1/legal/reminders/run-due", headers={"X-API-Key": ENV_ADMIN_KEY})
    db_session.refresh(reminder)

    assert result.status_code == 200
    assert reminder.status == "pending"
    assert reminder.last_error == "租户已关闭企业微信发送"


def test_ocr_disabled_by_feature_flag(client, db_session, monkeypatch, tmp_path):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"feature_flags": {"enable_ocr": False}})
    pdf_path = tmp_path / "a.pdf"
    pdf_path.write_bytes(b"pdf")

    result = OCRService().extract_from_file(str(pdf_path), "pdf", tenant_id="tenant_001")

    assert result["success"] is False
    assert result["error"] == "租户已关闭 OCR"


def test_tenant_keyword_config_affects_text_recognition(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"keyword_config": {"payment_notice": ["交费"], "payment_done": ["已付款"]}})

    result = OCRService().extract_from_text("案件(2026)黔0281民初3118号需要交费400元", tenant_id="tenant_001")

    assert result["event_type"] == "payment_notice"
    assert "交费" in result["keywords"]


def test_kdocs_case_sheet_used_in_sync_log(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"tencent_doc_case_sheet_name": "租户案件台账", "tencent_doc_archive_sheet_name": "租户资料台账"})
    legal_case = _case(db_session)

    response = client.post(f"/api/v1/legal/cases/{legal_case.id}/sync", headers={"X-API-Key": ENV_ADMIN_KEY})

    assert response.status_code == 200
    log = db_session.scalar(select(DocumentSyncLog).where(DocumentSyncLog.case_id == legal_case.id))
    payload = json.loads(log.request_payload_json)
    assert payload["payload"]["sheet_id"] == "致和法务/案件台账"
    assert log.sync_target == "kdocs"


def test_delete_tenant_settings_restores_global(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"ocr_provider": "local_text"})

    deleted = client.delete("/api/v1/legal/tenants/tenant_001/settings", headers={"X-API-Key": ENV_ADMIN_KEY})
    effective = TenantSettingsService(db_session).get_effective_settings("tenant_001")

    assert deleted.status_code == 200
    assert effective["source"] == "global"
    assert effective["ocr"]["provider"] == get_settings().ocr_provider


def test_tenant_settings_disabled_uses_global_config(client, db_session, monkeypatch):
    _enable_auth(monkeypatch)
    _tenant(db_session)
    _put_settings(client, {"ocr_provider": "local_text"})
    monkeypatch.setenv("TENANT_SETTINGS_ENABLED", "false")
    get_settings.cache_clear()

    effective = TenantSettingsService(db_session).get_effective_settings("tenant_001")

    assert effective["source"] == "global"
    assert effective["ocr"]["provider"] == os.environ.get("OCR_PROVIDER", "mock")


def test_seventh_migration_file_exists():
    assert (PROJECT_ROOT / "alembic" / "versions" / "0007_add_tenant_settings.py").exists()
