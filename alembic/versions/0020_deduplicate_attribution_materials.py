"""Deduplicate pending attribution items by source message.

Revision ID: 0020_attribution_materials
Revises: 0019_business_spec_defaults
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_attribution_materials"
down_revision: str | Sequence[str] | None = "0019_business_spec_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    db = op.get_bind()
    rows = db.execute(
        sa.text(
            """
            SELECT ai.id, ai.subject_type,
                   COALESCE(m.group_message_id, e.group_message_id) AS source_message_id
            FROM attribution_items ai
            LEFT JOIN legal_media_files m ON m.id = ai.media_file_id
            LEFT JOIN legal_events e ON e.id = ai.event_id
            WHERE ai.status = 'pending'
            ORDER BY source_message_id,
                     CASE ai.subject_type WHEN 'media' THEN 0 ELSE 1 END,
                     ai.id
            """
        )
    ).mappings()
    seen: set[int] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        message_id = row["source_message_id"]
        if message_id is None:
            continue
        if message_id in seen:
            duplicate_ids.append(int(row["id"]))
        else:
            seen.add(int(message_id))
    if duplicate_ids:
        db.execute(
            sa.text(
                """
                UPDATE attribution_items
                SET status = 'superseded',
                    reason = CASE
                        WHEN reason IS NULL OR reason = '' THEN '[0020] 已合并到同一来源消息的资料包'
                        ELSE reason || '；[0020] 已合并到同一来源消息的资料包'
                    END
                WHERE id IN :ids
                """
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": duplicate_ids},
        )


def downgrade() -> None:
    db = op.get_bind()
    db.execute(
        sa.text(
            """
            UPDATE attribution_items
            SET status = 'pending',
                reason = REPLACE(REPLACE(reason, '；[0020] 已合并到同一来源消息的资料包', ''), '[0020] 已合并到同一来源消息的资料包', '')
            WHERE status = 'superseded' AND reason LIKE '%[0020] 已合并到同一来源消息的资料包%'
            """
        )
    )
