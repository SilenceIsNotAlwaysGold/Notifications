from sqlalchemy import select

from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.media_file import MediaFile
from app.models.system_alert import SystemAlert
from app.services.system_alert_service import SystemAlertService


def test_alert_condition_is_deduplicated_acknowledged_and_resolved(db_session):
    service = SystemAlertService(db_session)
    condition = {
        "dedupe_key": "test:kdocs",
        "active": True,
        "alert_type": "kdocs_consecutive_failures",
        "severity": "critical",
        "source": "kdocs",
        "title": "金山文档同步连续失败",
        "message": "连续失败 3 次",
        "details": {"threshold": 3},
    }

    first_transition, first = service.reconcile_condition(**condition)
    second_transition, second = service.reconcile_condition(**condition)
    acknowledged = service.acknowledge(first.id, "admin-test")
    resolved_transition, resolved = service.reconcile_condition(**{**condition, "active": False})

    assert first_transition == "opened"
    assert second_transition is None
    assert first.id == second.id
    assert acknowledged.acknowledged_by == "admin-test"
    assert resolved_transition == "resolved"
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    assert len(list(db_session.scalars(select(SystemAlert)).all())) == 1


def test_scan_opens_and_recovers_kdocs_failure_alert(db_session, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups" / "fresh"
    backup_dir.mkdir(parents=True)
    (backup_dir / "manifest.json").write_text("{}", encoding="utf-8")
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setenv("OPS_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("OPS_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("OPS_DISK_FREE_MIN_GB", "0")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(media_dir))
    monkeypatch.setenv("WECOM_ARCHIVE_MODE", "mock")
    monkeypatch.setenv("WECOM_SEND_MODE", "mock")
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "regex")
    get_settings.cache_clear()

    logs = []
    for index in range(3):
        log = DocumentSyncLog(
            sync_type="court_time",
            sync_target="kdocs",
            idempotency_key=f"alert-kdocs-{index}",
            request_payload_json="{}",
            response_payload_json="{}",
            status="failed",
            retry_count=0,
        )
        db_session.add(log)
        logs.append(log)
    db_session.flush()

    first = SystemAlertService(db_session).scan()
    alert = db_session.scalar(select(SystemAlert).where(SystemAlert.alert_type == "kdocs_consecutive_failures"))
    logs[-1].status = "success"
    second = SystemAlertService(db_session).scan()

    assert first["opened"] == 1
    assert alert.status == "resolved"
    assert second["resolved"] == 1
    get_settings.cache_clear()


def test_system_alert_api_lists_and_acknowledges(client, db_session):
    _, alert = SystemAlertService(db_session).reconcile_condition(
        dedupe_key="test:api-alert",
        active=True,
        alert_type="disk_space_low",
        severity="critical",
        source="filesystem",
        title="磁盘空间不足",
        message="测试告警",
        details={},
    )
    db_session.commit()

    response = client.get("/api/v1/legal/system-alerts")
    ack_response = client.post(f"/api/v1/legal/system-alerts/{alert.id}/ack", json={})

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["alert_type"] == "disk_space_low"
    assert ack_response.status_code == 200
    assert ack_response.json()["data"]["status"] == "acknowledged"


def test_llm_fallbacks_are_read_from_structured_ocr_results(db_session, monkeypatch):
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "https://llm.test")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "legal-model")
    monkeypatch.setenv("OPS_FAILURE_THRESHOLD", "2")
    get_settings.cache_clear()
    for index in range(2):
        db_session.add(
            MediaFile(
                group_id="group_llm",
                msg_id=f"llm-{index}",
                media_type="pdf",
                source="wecom_archive",
                download_status="downloaded",
                ocr_status="processed",
                ocr_result_json='{"metadata":{"llm_status":"fallback"}}',
            )
        )
    db_session.flush()

    condition = SystemAlertService(db_session)._llm_condition()

    assert condition["active"] is True
    assert condition["details"]["statuses"] == ["fallback", "fallback"]
    get_settings.cache_clear()


def test_android_sender_offline_condition_is_sanitized(db_session, monkeypatch):
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "http://sender.internal:8092")
    monkeypatch.setenv("WECOMAPI_TOKEN", "sender-token")
    monkeypatch.setenv("WECOMAPI_GUID", "sender-device")
    monkeypatch.setattr(
        "app.services.system_alert_service.WeComSenderStatusClient.check",
        lambda self: {
            "status": "error",
            "message": "Android 发送设备未连接",
            "backend": "android",
            "configured": True,
            "online": False,
            "target_count": 1,
            "error_type": "ConnectError",
        },
    )
    get_settings.cache_clear()

    condition = SystemAlertService(db_session)._sender_condition()

    assert condition["active"] is True
    assert condition["alert_type"] == "wecom_sender_offline"
    assert condition["severity"] == "critical"
    assert condition["details"]["online"] is False
    assert "sender.internal" not in str(condition)
    get_settings.cache_clear()
