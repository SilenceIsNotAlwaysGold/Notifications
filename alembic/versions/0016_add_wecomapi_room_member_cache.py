"""add wecomapi room member cache

Revision ID: 0016_add_wecomapi_room_member_cache
Revises: 0015_add_wecomapi_room_cache
Create Date: 2026-07-24 01:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016_add_wecomapi_room_member_cache"
down_revision: Union[str, Sequence[str], None] = "0015_add_wecomapi_room_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wecomapi_room_member_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guid", sa.String(length=128), nullable=False),
        sa.Column("room_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "user_id", name="uq_wecomapi_room_member"),
    )
    op.create_index(op.f("ix_wecomapi_room_member_cache_id"), "wecomapi_room_member_cache", ["id"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_member_cache_guid"), "wecomapi_room_member_cache", ["guid"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_member_cache_room_id"), "wecomapi_room_member_cache", ["room_id"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_member_cache_user_id"), "wecomapi_room_member_cache", ["user_id"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_member_cache_source"), "wecomapi_room_member_cache", ["source"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_member_cache_last_seen_at"), "wecomapi_room_member_cache", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_table("wecomapi_room_member_cache")
