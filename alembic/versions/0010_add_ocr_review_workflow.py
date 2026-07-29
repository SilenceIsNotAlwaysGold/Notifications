"""add OCR review workflow

Revision ID: 0010_add_ocr_review_workflow
Revises: 0009_add_wecomapi_room_id
Create Date: 2026-07-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import column_names, index_names

revision: str = "0010_add_ocr_review_workflow"
down_revision: Union[str, Sequence[str], None] = "0009_add_wecomapi_room_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_media_columns = column_names(connection, "legal_media_files")
    media_columns = (
        sa.Column("ocr_result_json", sa.Text(), nullable=True),
        sa.Column("review_result_json", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="not_required"),
        sa.Column("review_event_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("business_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    missing_media_columns = [column for column in media_columns if column.name not in existing_media_columns]
    if missing_media_columns:
        with op.batch_alter_table("legal_media_files") as batch_op:
            for column in missing_media_columns:
                batch_op.add_column(column)
    media_indexes = index_names(connection, "legal_media_files")
    for index_name, columns in (
        (op.f("ix_legal_media_files_review_status"), ["review_status"]),
        (op.f("ix_legal_media_files_review_event_id"), ["review_event_id"]),
    ):
        if index_name not in media_indexes:
            op.create_index(index_name, "legal_media_files", columns, unique=False)

    # Older processed rows already executed their downstream side effects. Mark
    # them complete so upgrading cannot replay money or document operations.
    op.execute(
        "UPDATE legal_media_files SET review_status = 'approved', "
        "business_applied_at = updated_at WHERE ocr_status = 'processed'"
    )

    existing_reminder_columns = column_names(connection, "reminders")
    reminder_columns = (
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
    )
    missing_reminder_columns = [column for column in reminder_columns if column.name not in existing_reminder_columns]
    if missing_reminder_columns:
        with op.batch_alter_table("reminders") as batch_op:
            for column in missing_reminder_columns:
                batch_op.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_column("cancel_reason")
        batch_op.drop_column("cancelled_at")

    with op.batch_alter_table("legal_media_files") as batch_op:
        batch_op.drop_index(op.f("ix_legal_media_files_review_event_id"))
        batch_op.drop_index(op.f("ix_legal_media_files_review_status"))
        batch_op.drop_column("business_applied_at")
        batch_op.drop_column("review_note")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("review_event_id")
        batch_op.drop_column("review_status")
        batch_op.drop_column("review_result_json")
        batch_op.drop_column("ocr_result_json")
