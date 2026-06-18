"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legal_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_no", sa.String(length=128), nullable=False),
        sa.Column("debtor_name", sa.String(length=128), nullable=False),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("debtor_wecom_userid", sa.String(length=128), nullable=True),
        sa.Column("lawyer_wecom_userid", sa.String(length=128), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("overdue_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("defaulted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("repayment_reminder_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("default_upgrade_reminder_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_legal_cases_case_no"), "legal_cases", ["case_no"], unique=True)
    op.create_index(op.f("ix_legal_cases_debtor_name"), "legal_cases", ["debtor_name"], unique=False)
    op.create_index(op.f("ix_legal_cases_group_id"), "legal_cases", ["group_id"], unique=False)
    op.create_index(op.f("ix_legal_cases_status"), "legal_cases", ["status"], unique=False)

    op.create_table(
        "group_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("msg_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("file_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_group_messages_group_id"), "group_messages", ["group_id"], unique=False)
    op.create_index(op.f("ix_group_messages_msg_type"), "group_messages", ["msg_type"], unique=False)
    op.create_index(op.f("ix_group_messages_received_at"), "group_messages", ["received_at"], unique=False)
    op.create_index(op.f("ix_group_messages_sender_id"), "group_messages", ["sender_id"], unique=False)

    op.create_table(
        "legal_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("group_message_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["legal_cases.id"]),
        sa.ForeignKeyConstraint(["group_message_id"], ["group_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_legal_events_case_id"), "legal_events", ["case_id"], unique=False)
    op.create_index(op.f("ix_legal_events_event_type"), "legal_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_legal_events_group_message_id"), "legal_events", ["group_message_id"], unique=False)

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("reminder_type", sa.String(length=64), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("target_userid", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["legal_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminders_case_id"), "reminders", ["case_id"], unique=False)
    op.create_index(op.f("ix_reminders_group_id"), "reminders", ["group_id"], unique=False)
    op.create_index(op.f("ix_reminders_remind_at"), "reminders", ["remind_at"], unique=False)
    op.create_index(op.f("ix_reminders_reminder_type"), "reminders", ["reminder_type"], unique=False)
    op.create_index(op.f("ix_reminders_status"), "reminders", ["status"], unique=False)

    op.create_table(
        "document_sync_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("sync_type", sa.String(length=64), nullable=False),
        sa.Column("sync_target", sa.String(length=64), nullable=True),
        sa.Column("external_doc_id", sa.String(length=128), nullable=True),
        sa.Column("external_sheet_name", sa.String(length=128), nullable=True),
        sa.Column("external_row_key", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_payload_json", sa.Text(), nullable=False),
        sa.Column("response_payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["legal_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_document_sync_logs_case_id"), "document_sync_logs", ["case_id"], unique=False)
    op.create_index(op.f("ix_document_sync_logs_idempotency_key"), "document_sync_logs", ["idempotency_key"], unique=False)
    op.create_index(op.f("ix_document_sync_logs_status"), "document_sync_logs", ["status"], unique=False)
    op.create_index(op.f("ix_document_sync_logs_sync_target"), "document_sync_logs", ["sync_target"], unique=False)
    op.create_index(op.f("ix_document_sync_logs_sync_type"), "document_sync_logs", ["sync_type"], unique=False)

    op.create_table(
        "legal_media_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_message_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("msg_id", sa.String(length=128), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("file_ext", sa.String(length=32), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("md5sum", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_payload_json", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("download_status", sa.String(length=32), nullable=False),
        sa.Column("ocr_status", sa.String(length=32), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["legal_cases.id"]),
        sa.ForeignKeyConstraint(["group_message_id"], ["group_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_legal_media_files_case_id"), "legal_media_files", ["case_id"], unique=False)
    op.create_index(op.f("ix_legal_media_files_download_status"), "legal_media_files", ["download_status"], unique=False)
    op.create_index(op.f("ix_legal_media_files_group_id"), "legal_media_files", ["group_id"], unique=False)
    op.create_index(op.f("ix_legal_media_files_group_message_id"), "legal_media_files", ["group_message_id"], unique=False)
    op.create_index(op.f("ix_legal_media_files_media_type"), "legal_media_files", ["media_type"], unique=False)
    op.create_index(op.f("ix_legal_media_files_msg_id"), "legal_media_files", ["msg_id"], unique=False)
    op.create_index(op.f("ix_legal_media_files_ocr_status"), "legal_media_files", ["ocr_status"], unique=False)
    op.create_index(op.f("ix_legal_media_files_seq"), "legal_media_files", ["seq"], unique=False)
    op.create_index(op.f("ix_legal_media_files_source"), "legal_media_files", ["source"], unique=False)

    op.create_table(
        "system_run_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_run_logs_run_type"), "system_run_logs", ["run_type"], unique=False)
    op.create_index(op.f("ix_system_run_logs_status"), "system_run_logs", ["status"], unique=False)
    op.create_index(op.f("ix_system_run_logs_trigger_type"), "system_run_logs", ["trigger_type"], unique=False)

    op.create_table(
        "case_status_histories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["legal_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_case_status_histories_case_id"), "case_status_histories", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_status_histories_new_status"), "case_status_histories", ["new_status"], unique=False)
    op.create_index(op.f("ix_case_status_histories_reason"), "case_status_histories", ["reason"], unique=False)

    op.create_table(
        "reminder_send_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reminder_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("target_userid", sa.String(length=128), nullable=True),
        sa.Column("send_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_payload_json", sa.Text(), nullable=True),
        sa.Column("response_payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminder_send_logs_group_id"), "reminder_send_logs", ["group_id"], unique=False)
    op.create_index(op.f("ix_reminder_send_logs_reminder_id"), "reminder_send_logs", ["reminder_id"], unique=False)
    op.create_index(op.f("ix_reminder_send_logs_send_mode"), "reminder_send_logs", ["send_mode"], unique=False)
    op.create_index(op.f("ix_reminder_send_logs_status"), "reminder_send_logs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_reminder_send_logs_status"), table_name="reminder_send_logs")
    op.drop_index(op.f("ix_reminder_send_logs_send_mode"), table_name="reminder_send_logs")
    op.drop_index(op.f("ix_reminder_send_logs_reminder_id"), table_name="reminder_send_logs")
    op.drop_index(op.f("ix_reminder_send_logs_group_id"), table_name="reminder_send_logs")
    op.drop_table("reminder_send_logs")

    op.drop_index(op.f("ix_case_status_histories_reason"), table_name="case_status_histories")
    op.drop_index(op.f("ix_case_status_histories_new_status"), table_name="case_status_histories")
    op.drop_index(op.f("ix_case_status_histories_case_id"), table_name="case_status_histories")
    op.drop_table("case_status_histories")

    op.drop_index(op.f("ix_system_run_logs_trigger_type"), table_name="system_run_logs")
    op.drop_index(op.f("ix_system_run_logs_status"), table_name="system_run_logs")
    op.drop_index(op.f("ix_system_run_logs_run_type"), table_name="system_run_logs")
    op.drop_table("system_run_logs")

    op.drop_index(op.f("ix_legal_media_files_source"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_seq"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_ocr_status"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_msg_id"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_media_type"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_group_message_id"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_group_id"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_download_status"), table_name="legal_media_files")
    op.drop_index(op.f("ix_legal_media_files_case_id"), table_name="legal_media_files")
    op.drop_table("legal_media_files")

    op.drop_index(op.f("ix_document_sync_logs_sync_type"), table_name="document_sync_logs")
    op.drop_index(op.f("ix_document_sync_logs_sync_target"), table_name="document_sync_logs")
    op.drop_index(op.f("ix_document_sync_logs_status"), table_name="document_sync_logs")
    op.drop_index(op.f("ix_document_sync_logs_idempotency_key"), table_name="document_sync_logs")
    op.drop_index(op.f("ix_document_sync_logs_case_id"), table_name="document_sync_logs")
    op.drop_table("document_sync_logs")

    op.drop_index(op.f("ix_reminders_status"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_reminder_type"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_remind_at"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_group_id"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_case_id"), table_name="reminders")
    op.drop_table("reminders")

    op.drop_index(op.f("ix_legal_events_group_message_id"), table_name="legal_events")
    op.drop_index(op.f("ix_legal_events_event_type"), table_name="legal_events")
    op.drop_index(op.f("ix_legal_events_case_id"), table_name="legal_events")
    op.drop_table("legal_events")

    op.drop_index(op.f("ix_group_messages_sender_id"), table_name="group_messages")
    op.drop_index(op.f("ix_group_messages_received_at"), table_name="group_messages")
    op.drop_index(op.f("ix_group_messages_msg_type"), table_name="group_messages")
    op.drop_index(op.f("ix_group_messages_group_id"), table_name="group_messages")
    op.drop_table("group_messages")

    op.drop_index(op.f("ix_legal_cases_status"), table_name="legal_cases")
    op.drop_index(op.f("ix_legal_cases_group_id"), table_name="legal_cases")
    op.drop_index(op.f("ix_legal_cases_debtor_name"), table_name="legal_cases")
    op.drop_index(op.f("ix_legal_cases_case_no"), table_name="legal_cases")
    op.drop_table("legal_cases")
