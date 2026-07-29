from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.compat import ensure_sqlite_compat_columns
from app.models.legal_case import LegalCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "case_candidates",
    "legal_cases",
    "group_messages",
    "legal_events",
    "reminders",
    "document_sync_logs",
    "legal_media_files",
    "system_run_logs",
    "case_status_histories",
    "reminder_send_logs",
    "operation_audit_logs",
    "api_keys",
    "tenants",
    "tenant_settings",
    "wecom_archive_groups",
    "wecomapi_room_cache",
    "wecomapi_room_member_cache",
    "reminder_rules",
    "merchant_questions",
    "system_alerts",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_alembic_env_uses_model_metadata():
    assert EXPECTED_TABLES <= set(Base.metadata.tables.keys())
    assert (PROJECT_ROOT / "alembic" / "env.py").exists()


def test_initial_migration_file_exists():
    assert (PROJECT_ROOT / "alembic" / "versions" / "0001_initial_schema.py").exists()


def test_base_metadata_contains_all_current_tables():
    assert EXPECTED_TABLES <= set(Base.metadata.tables.keys())


def test_alembic_upgrade_head_succeeds_with_temp_sqlite(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'upgrade_head.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    command.upgrade(_alembic_config(database_url), "head")

    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert EXPECTED_TABLES <= set(inspector.get_table_names())
        assert "wecomapi_room_id" in {column["name"] for column in inspector.get_columns("wecom_archive_groups")}
        assert "dedupe_key" in {column["name"] for column in inspector.get_columns("reminders")}
        assert "group_type" in {column["name"] for column in inspector.get_columns("wecom_archive_groups")}
        assert "access_policy" in {column["name"] for column in inspector.get_columns("wecom_archive_groups")}
        assert "applies_to_event_id" in {column["name"] for column in inspector.get_columns("payment_records")}
        assert "processing_mode" in {column["name"] for column in inspector.get_columns("group_messages")}
        assert "live_since_at" in {column["name"] for column in inspector.get_columns("wecom_archive_groups")}
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_upgrade_repairs_legacy_database_with_autocreated_future_tables(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'autocreated_drift.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    command.upgrade(config, "0007_add_tenant_settings")

    engine = create_engine(database_url, future=True)
    try:
        Base.metadata.create_all(engine)
        ensure_sqlite_compat_columns(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO contacts "
                    "(display_name,role,source,is_active,created_at,updated_at) "
                    "VALUES ('迁移保留联系人','lawyer','legacy-autocreate',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO group_messages "
                    "(group_id,sender_id,msg_type,content,raw_payload_json,received_at,created_at) "
                    "VALUES ('legacy_drift_group','legacy_sender','text','案件受理费 25 元','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            message_id = connection.execute(
                text("SELECT id FROM group_messages WHERE group_id='legacy_drift_group'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO legal_events "
                    "(group_message_id,event_type,amount,metadata_json,created_at) "
                    "VALUES (:message_id,'payment_notice',25,'{}',CURRENT_TIMESTAMP)"
                ),
                {"message_id": message_id},
            )

        command.upgrade(config, "head")

        inspector = inspect(engine)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            contact = connection.execute(
                text("SELECT display_name,source FROM contacts WHERE display_name='迁移保留联系人'")
            ).mappings().one()
            event = connection.execute(
                text(
                    "SELECT attribution_status,business_status FROM legal_events "
                    "WHERE group_message_id=:message_id"
                ),
                {"message_id": message_id},
            ).mappings().one()
            attribution_count = connection.execute(
                text("SELECT COUNT(*) FROM attribution_items WHERE subject_type='event'")
            ).scalar_one()
        assert revision == "0022_processing_modes"
        assert dict(contact) == {"display_name": "迁移保留联系人", "source": "legacy-autocreate"}
        assert dict(event) == {"attribution_status": "pending", "business_status": "staged"}
        assert attribution_count == 1
        assert "processing_mode" in {column["name"] for column in inspector.get_columns("group_messages")}
        assert "target_contact_id" in {column["name"] for column in inspector.get_columns("reminders")}
        assert "applies_to_event_id" in {column["name"] for column in inspector.get_columns("payment_records")}
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_can_create_case_after_alembic_upgrade(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'create_case.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(_alembic_config(database_url), "head")

    engine = create_engine(database_url, connect_args={"check_same_thread": False}, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        with SessionLocal() as db:
            case = LegalCase(
                case_no="(2026)黔0281民初9001号",
                debtor_name="迁移测试",
                group_id="group_migration",
                due_date=date(2026, 6, 30),
                total_amount=Decimal("1000.00"),
                paid_amount=Decimal("0.00"),
            )
            db.add(case)
            db.commit()

            saved = db.scalar(select(LegalCase).where(LegalCase.case_no == "(2026)黔0281民初9001号"))
            assert saved is not None
            assert saved.id is not None
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_attribution_material_migration_supersedes_same_message_event(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'attribution_materials.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    command.upgrade(config, "0019_business_spec_defaults")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO group_messages (group_id,sender_id,msg_type,raw_payload_json,received_at,created_at) "
                    "VALUES ('group_001','u1','image','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            message_id = connection.execute(text("SELECT id FROM group_messages")).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO legal_media_files "
                    "(group_message_id,group_id,media_type,source,download_status,ocr_status,review_status,created_at,updated_at) "
                    "VALUES (:message_id,'group_001','image','test','downloaded','processed','pending',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {"message_id": message_id},
            )
            media_id = connection.execute(text("SELECT id FROM legal_media_files")).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO legal_events "
                    "(group_message_id,event_type,metadata_json,attribution_status,business_status,created_at) "
                    "VALUES (:message_id,'payment_screenshot','{}','pending','staged',CURRENT_TIMESTAMP)"
                ),
                {"message_id": message_id},
            )
            event_id = connection.execute(text("SELECT id FROM legal_events")).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO attribution_items "
                    "(group_id,subject_type,subject_id,media_file_id,evidence_json,status,created_at,updated_at) VALUES "
                    "('group_001','media',:media_id,:media_id,'{}','pending',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
                    "('group_001','event',:event_id,:event_id,'{}','pending',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                ),
                {"media_id": media_id, "event_id": event_id},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            rows = connection.execute(text("SELECT subject_type,status,reason FROM attribution_items ORDER BY id")).mappings().all()
            event = connection.execute(text("SELECT attribution_status,business_status FROM legal_events WHERE id=:id"), {"id": event_id}).mappings().one()
            outbox_count = connection.execute(text("SELECT COUNT(*) FROM business_outbox")).scalar_one()
            payment_count = connection.execute(text("SELECT COUNT(*) FROM payment_records")).scalar_one()
            reminder_count = connection.execute(text("SELECT COUNT(*) FROM reminders")).scalar_one()
            sync_count = connection.execute(text("SELECT COUNT(*) FROM document_sync_logs")).scalar_one()
        assert [dict(row) for row in rows] == [
            {"subject_type": "media", "status": "pending", "reason": None},
            {"subject_type": "event", "status": "superseded", "reason": "[0020] 已合并到同一来源消息的资料包"},
        ]
        assert dict(event) == {"attribution_status": "pending", "business_status": "staged"}
        assert (outbox_count, payment_count, reminder_count, sync_count) == (0, 0, 0, 0)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_sync_idempotency_migration_keeps_first_key_and_renames_legacy_duplicates(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'sync_idempotency.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    command.upgrade(config, "0011_business_rules")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            for _ in range(3):
                connection.execute(
                    text(
                        """
                        INSERT INTO document_sync_logs (
                            sync_type, idempotency_key, request_payload_json,
                            response_payload_json, status, retry_count, created_at
                        ) VALUES (
                            'court_time', 'duplicate-key', '{}', '{}', 'success', 0,
                            '2026-07-20 03:00:00'
                        )
                        """
                    )
                )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            keys = list(
                connection.execute(
                    text("SELECT idempotency_key FROM document_sync_logs ORDER BY id")
                ).scalars()
            )
        index = next(
            item
            for item in inspect(engine).get_indexes("document_sync_logs")
            if item["name"] == "ix_document_sync_logs_idempotency_key"
        )
        assert keys[0] == "duplicate-key"
        assert keys[1].startswith("legacy:2:duplicate-key")
        assert keys[2].startswith("legacy:3:duplicate-key")
        assert index["unique"] == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_upgrade_from_0009_preserves_old_ocr_and_reminder_rows(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'upgrade_from_0009.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    command.upgrade(config, "0009_add_wecomapi_room_id")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO legal_media_files (
                        group_id, media_type, source, download_status, ocr_status,
                        extracted_text, created_at, updated_at
                    ) VALUES (
                        'group_legacy', 'pdf', 'wecom_archive', 'downloaded', 'processed',
                        '历史判决书 OCR', '2026-07-01 09:00:00', '2026-07-01 09:05:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO reminders (
                        group_id, reminder_type, remind_at, content, status,
                        retry_count, created_at, updated_at
                    ) VALUES (
                        'group_legacy', 'payment_tracking', '2026-07-02 09:00:00',
                        '历史缴费提醒', 'pending', 0,
                        '2026-07-01 09:00:00', '2026-07-01 09:00:00'
                    )
                    """
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            media = connection.execute(
                text("SELECT extracted_text, review_status, business_applied_at FROM legal_media_files")
            ).mappings().one()
            reminder = connection.execute(
                text("SELECT content, cancelled_at, dedupe_key FROM reminders")
            ).mappings().one()
        assert media["extracted_text"] == "历史判决书 OCR"
        assert media["review_status"] == "approved"
        assert media["business_applied_at"] is not None
        assert reminder["content"] == "历史缴费提醒"
        assert reminder["cancelled_at"] is None
        assert reminder["dedupe_key"] is None
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_db_auto_create_false_skips_startup_create_all(monkeypatch):
    from app import main as app_main

    called = {"create_all": 0, "compat": 0}

    def fake_create_all(*args, **kwargs):
        called["create_all"] += 1

    def fake_compat(*args, **kwargs):
        called["compat"] += 1

    monkeypatch.setenv("DB_AUTO_CREATE", "false")
    monkeypatch.setattr(app_main.Base.metadata, "create_all", fake_create_all)
    monkeypatch.setattr(app_main, "ensure_sqlite_compat_columns", fake_compat)
    get_settings.cache_clear()

    app_main.initialize_database()

    assert called == {"create_all": 0, "compat": 0}
    get_settings.cache_clear()


def test_business_defaults_migration_preserves_customized_global_rule(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'custom_rule.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config(database_url)
    command.upgrade(config, "0018_kdocs_row_metadata")
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO reminder_rules "
                    "(tenant_id,name,rule_type,offset_days,send_time,target_role,template,sort_order,enabled,created_at,updated_at) "
                    "VALUES (NULL,'缴费 D+0','payment_tracking',0,'10:30','lawyer','人工定制话术',0,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            customized = connection.execute(
                text("SELECT send_time, template FROM reminder_rules WHERE tenant_id IS NULL AND name='缴费 D+0'")
            ).mappings().one()
        assert dict(customized) == {"send_time": "10:30", "template": "人工定制话术"}
    finally:
        engine.dispose()
        get_settings.cache_clear()
