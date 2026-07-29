"""Add message processing modes and archive live watermark.

Revision ID: 0022_processing_modes
Revises: 0021_payment_allocations
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import column_names, index_names


revision: str = "0022_processing_modes"
down_revision: str | Sequence[str] | None = "0021_payment_allocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    needs_processing_mode = "processing_mode" not in column_names(connection, "group_messages")
    needs_processing_index = "ix_group_messages_processing_mode" not in index_names(connection, "group_messages")
    if needs_processing_mode or needs_processing_index:
        with op.batch_alter_table("group_messages") as batch:
            if needs_processing_mode:
                batch.add_column(sa.Column("processing_mode", sa.String(length=32), nullable=False, server_default="live"))
            if needs_processing_index:
                batch.create_index("ix_group_messages_processing_mode", ["processing_mode"])
    if "live_since_at" not in column_names(connection, "wecom_archive_groups"):
        with op.batch_alter_table("wecom_archive_groups") as batch:
            batch.add_column(sa.Column("live_since_at", sa.DateTime(), nullable=True))
    if "classification_json" not in column_names(connection, "merchant_questions"):
        with op.batch_alter_table("merchant_questions") as batch:
            batch.add_column(sa.Column("classification_json", sa.Text(), nullable=False, server_default="{}"))

    op.execute(
        "UPDATE legal_events SET business_status='superseded', attribution_status='not_required' "
        "WHERE event_type IN ('unknown','keyword') AND business_status='staged'"
    )
    op.execute(
        "UPDATE legal_media_files SET review_status='not_required', review_note='历史非业务材料已自动隔离' "
        "WHERE review_status='pending' AND review_event_id IN "
        "(SELECT id FROM legal_events WHERE event_type IN ('unknown','keyword'))"
    )
    op.execute(
        "UPDATE reminders SET status='cancelled', cancelled_at=CURRENT_TIMESTAMP, "
        "cancel_reason='发布前历史商家提醒已隔离' "
        "WHERE status='pending' AND reminder_type LIKE 'merchant_question_%'"
    )
    op.execute(
        "UPDATE merchant_questions SET status='closed', closed_by='system:migration', "
        "closed_at=CURRENT_TIMESTAMP, close_reason='发布前历史任务已隔离' "
        "WHERE status IN ('open','timed_out','escalated')"
    )


def downgrade() -> None:
    with op.batch_alter_table("merchant_questions") as batch:
        batch.drop_column("classification_json")
    with op.batch_alter_table("wecom_archive_groups") as batch:
        batch.drop_column("live_since_at")
    with op.batch_alter_table("group_messages") as batch:
        batch.drop_index("ix_group_messages_processing_mode")
        batch.drop_column("processing_mode")
