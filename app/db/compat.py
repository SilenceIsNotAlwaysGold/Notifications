from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_sqlite_compat_columns(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "reminders" in inspector.get_table_names():
        column_names = {column["name"] for column in inspector.get_columns("reminders")}
        if "sent_at" not in column_names:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE reminders ADD COLUMN sent_at DATETIME"))
    _ensure_legal_case_columns(engine, inspector)
    _ensure_document_sync_log_columns(engine, inspector)


def _ensure_legal_case_columns(engine: Engine, inspector) -> None:
    if "legal_cases" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("legal_cases")}
    columns = {
        "overdue_at": "DATETIME",
        "defaulted_at": "DATETIME",
        "paid_at": "DATETIME",
        "last_status_checked_at": "DATETIME",
        "repayment_reminder_created_at": "DATETIME",
        "default_upgrade_reminder_created_at": "DATETIME",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in column_names:
                connection.execute(text(f"ALTER TABLE legal_cases ADD COLUMN {column_name} {column_type}"))


def _ensure_document_sync_log_columns(engine: Engine, inspector) -> None:
    if "document_sync_logs" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("document_sync_logs")}
    columns = {
        "sync_target": "VARCHAR(64)",
        "external_doc_id": "VARCHAR(128)",
        "external_sheet_name": "VARCHAR(128)",
        "external_row_key": "VARCHAR(255)",
        "idempotency_key": "VARCHAR(255)",
        "retry_count": "INTEGER DEFAULT 0",
        "last_attempt_at": "DATETIME",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in column_names:
                connection.execute(text(f"ALTER TABLE document_sync_logs ADD COLUMN {column_name} {column_type}"))
