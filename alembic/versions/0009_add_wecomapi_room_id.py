"""add wecomapi room id mapping

Revision ID: 0009_add_wecomapi_room_id
Revises: 0008_add_wecom_archive_groups
Create Date: 2026-07-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import column_names, index_names

revision: str = "0009_add_wecomapi_room_id"
down_revision: Union[str, Sequence[str], None] = "0008_add_wecom_archive_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    if "wecomapi_room_id" not in column_names(connection, "wecom_archive_groups"):
        op.add_column("wecom_archive_groups", sa.Column("wecomapi_room_id", sa.String(length=128), nullable=True))
    index_name = op.f("ix_wecom_archive_groups_wecomapi_room_id")
    if index_name not in index_names(connection, "wecom_archive_groups"):
        op.create_index(index_name, "wecom_archive_groups", ["wecomapi_room_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_wecom_archive_groups_wecomapi_room_id"), table_name="wecom_archive_groups")
    op.drop_column("wecom_archive_groups", "wecomapi_room_id")
