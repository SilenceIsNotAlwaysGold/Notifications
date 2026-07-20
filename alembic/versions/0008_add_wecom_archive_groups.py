"""add wecom archive groups

Revision ID: 0008_add_wecom_archive_groups
Revises: 0007_add_tenant_settings
Create Date: 2026-07-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_add_wecom_archive_groups"
down_revision: Union[str, Sequence[str], None] = "0007_add_tenant_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wecom_archive_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("seen_message_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_wecom_archive_groups_id"), "wecom_archive_groups", ["id"], unique=False)
    op.create_index(op.f("ix_wecom_archive_groups_room_id"), "wecom_archive_groups", ["room_id"], unique=True)
    op.create_index(op.f("ix_wecom_archive_groups_status"), "wecom_archive_groups", ["status"], unique=False)
    op.create_index(op.f("ix_wecom_archive_groups_tenant_id"), "wecom_archive_groups", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_wecom_archive_groups_tenant_id"), table_name="wecom_archive_groups")
    op.drop_index(op.f("ix_wecom_archive_groups_status"), table_name="wecom_archive_groups")
    op.drop_index(op.f("ix_wecom_archive_groups_room_id"), table_name="wecom_archive_groups")
    op.drop_index(op.f("ix_wecom_archive_groups_id"), table_name="wecom_archive_groups")
    op.drop_table("wecom_archive_groups")
