"""add case candidates

Revision ID: 0014_add_case_candidates
Revises: 0013_system_alerts
Create Date: 2026-07-23 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014_add_case_candidates"
down_revision: Union[str, Sequence[str], None] = "0013_system_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_case_no", sa.String(length=128), nullable=False),
        sa.Column("case_no", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("debtor_name", sa.String(length=128), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_media_file_id", sa.Integer(), nullable=True),
        sa.Column("extracted_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_case_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", sa.String(length=128), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["confirmed_case_id"], ["legal_cases.id"]),
        sa.ForeignKeyConstraint(["source_media_file_id"], ["legal_media_files.id"]),
        sa.ForeignKeyConstraint(["source_message_id"], ["group_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in [
        "id",
        "case_no",
        "tenant_id",
        "group_id",
        "source_message_id",
        "source_media_file_id",
        "status",
        "confirmed_case_id",
    ]:
        op.create_index(op.f(f"ix_case_candidates_{column}"), "case_candidates", [column], unique=False)
    op.create_index(
        op.f("ix_case_candidates_normalized_case_no"),
        "case_candidates",
        ["normalized_case_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("case_candidates")
