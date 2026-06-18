from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.models.legal_case import LegalCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
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
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
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
