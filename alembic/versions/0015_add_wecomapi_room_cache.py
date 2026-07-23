"""add wecomapi room cache

Revision ID: 0015_add_wecomapi_room_cache
Revises: 0014_add_case_candidates
Create Date: 2026-07-24 00:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015_add_wecomapi_room_cache"
down_revision: Union[str, Sequence[str], None] = "0014_add_case_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wecomapi_room_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guid", sa.String(length=128), nullable=False),
        sa.Column("room_id", sa.String(length=128), nullable=False),
        sa.Column("room_name", sa.String(length=255), nullable=True),
        sa.Column("owner_userid", sa.String(length=128), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_wecomapi_room_cache_id"), "wecomapi_room_cache", ["id"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_cache_guid"), "wecomapi_room_cache", ["guid"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_cache_room_id"), "wecomapi_room_cache", ["room_id"], unique=True)
    op.create_index(op.f("ix_wecomapi_room_cache_source"), "wecomapi_room_cache", ["source"], unique=False)
    op.create_index(op.f("ix_wecomapi_room_cache_last_seen_at"), "wecomapi_room_cache", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_table("wecomapi_room_cache")
