"""add system alerts

Revision ID: 0013_system_alerts
Revises: 0012_sync_idempotency
Create Date: 2026-07-20 04:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013_system_alerts"
down_revision: Union[str, Sequence[str], None] = "0012_sync_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_alerts_id"), "system_alerts", ["id"], unique=False)
    op.create_index(op.f("ix_system_alerts_tenant_id"), "system_alerts", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_system_alerts_alert_type"), "system_alerts", ["alert_type"], unique=False)
    op.create_index(op.f("ix_system_alerts_severity"), "system_alerts", ["severity"], unique=False)
    op.create_index(op.f("ix_system_alerts_source"), "system_alerts", ["source"], unique=False)
    op.create_index(op.f("ix_system_alerts_dedupe_key"), "system_alerts", ["dedupe_key"], unique=True)
    op.create_index(op.f("ix_system_alerts_status"), "system_alerts", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("system_alerts")
