from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_sqlite_compat_columns(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "reminders" in inspector.get_table_names():
        column_names = {column["name"] for column in inspector.get_columns("reminders")}
        with engine.begin() as connection:
            if "sent_at" not in column_names:
                connection.execute(text("ALTER TABLE reminders ADD COLUMN sent_at DATETIME"))
            if "cancelled_at" not in column_names:
                connection.execute(text("ALTER TABLE reminders ADD COLUMN cancelled_at DATETIME"))
            if "cancel_reason" not in column_names:
                connection.execute(text("ALTER TABLE reminders ADD COLUMN cancel_reason TEXT"))
    _ensure_legal_case_columns(engine, inspector)
    _ensure_document_sync_log_columns(engine, inspector)
    _ensure_media_review_columns(engine, inspector)
    _ensure_reminder_rule_columns(engine, inspector)
    _ensure_archive_group_feature_columns(engine, inspector)


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


def _ensure_media_review_columns(engine: Engine, inspector) -> None:
    if "legal_media_files" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("legal_media_files")}
    columns = {
        "ocr_result_json": "TEXT",
        "review_result_json": "TEXT",
        "review_status": "VARCHAR(32) DEFAULT 'not_required'",
        "review_event_id": "INTEGER",
        "reviewed_by": "VARCHAR(128)",
        "reviewed_at": "DATETIME",
        "review_note": "TEXT",
        "business_applied_at": "DATETIME",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in column_names:
                connection.execute(text(f"ALTER TABLE legal_media_files ADD COLUMN {column_name} {column_type}"))


def _ensure_reminder_rule_columns(engine: Engine, inspector) -> None:
    if "reminders" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("reminders")}
    columns = {
        "rule_id": "INTEGER",
        "source_event_id": "INTEGER",
        "dedupe_key": "VARCHAR(255)",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in column_names:
                connection.execute(text(f"ALTER TABLE reminders ADD COLUMN {column_name} {column_type}"))


def _ensure_archive_group_feature_columns(engine: Engine, inspector) -> None:
    if "wecom_archive_groups" not in inspector.get_table_names():
        return
    column_names = {column["name"] for column in inspector.get_columns("wecom_archive_groups")}
    columns = {
        "group_type": "VARCHAR(32) DEFAULT 'other'",
        "access_policy": "VARCHAR(32) DEFAULT 'auto'",
        "features_json": "TEXT DEFAULT '{}'",
        "internal_userids_json": "TEXT DEFAULT '[]'",
        "alert_userids_json": "TEXT DEFAULT '[]'",
        "question_timeout_minutes": "INTEGER DEFAULT 5",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in column_names:
                connection.execute(text(f"ALTER TABLE wecom_archive_groups ADD COLUMN {column_name} {column_type}"))
