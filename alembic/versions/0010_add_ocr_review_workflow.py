"""add OCR review workflow

Revision ID: 0010_add_ocr_review_workflow
Revises: 0009_add_wecomapi_room_id
Create Date: 2026-07-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010_add_ocr_review_workflow"
down_revision: Union[str, Sequence[str], None] = "0009_add_wecomapi_room_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("legal_media_files") as batch_op:
        batch_op.add_column(sa.Column("ocr_result_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("review_result_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("review_status", sa.String(length=32), nullable=False, server_default="not_required"))
        batch_op.add_column(sa.Column("review_event_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("review_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("business_applied_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(op.f("ix_legal_media_files_review_status"), ["review_status"], unique=False)
        batch_op.create_index(op.f("ix_legal_media_files_review_event_id"), ["review_event_id"], unique=False)

    # Older processed rows already executed their downstream side effects. Mark
    # them complete so upgrading cannot replay money or document operations.
    op.execute(
        "UPDATE legal_media_files SET review_status = 'approved', "
        "business_applied_at = updated_at WHERE ocr_status = 'processed'"
    )

    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_reason", sa.Text(), nullable=True))


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
