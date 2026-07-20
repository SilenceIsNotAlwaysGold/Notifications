"""make document sync idempotency keys unique

Revision ID: 0012_sync_idempotency
Revises: 0011_business_rules
Create Date: 2026-07-20 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_sync_idempotency"
down_revision: Union[str, Sequence[str], None] = "0011_business_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_keys = connection.execute(
        sa.text(
            """
            SELECT idempotency_key
            FROM document_sync_logs
            WHERE idempotency_key IS NOT NULL
            GROUP BY idempotency_key
            HAVING COUNT(*) > 1
            """
        )
    ).scalars()
    for idempotency_key in duplicate_keys:
        duplicate_ids = list(
            connection.execute(
                sa.text(
                    """
                    SELECT id
                    FROM document_sync_logs
                    WHERE idempotency_key = :idempotency_key
                    ORDER BY id
                    """
                ),
                {"idempotency_key": idempotency_key},
            ).scalars()
        )
        for log_id in duplicate_ids[1:]:
            legacy_key = f"legacy:{log_id}:{idempotency_key}"
            connection.execute(
                sa.text(
                    """
                    UPDATE document_sync_logs
                    SET idempotency_key = :legacy_key
                    WHERE id = :log_id
                    """
                ),
                {"legacy_key": legacy_key[:255], "log_id": log_id},
            )

    with op.batch_alter_table("document_sync_logs") as batch_op:
        batch_op.drop_index(op.f("ix_document_sync_logs_idempotency_key"))
        batch_op.create_index(
            op.f("ix_document_sync_logs_idempotency_key"),
            ["idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("document_sync_logs") as batch_op:
        batch_op.drop_index(op.f("ix_document_sync_logs_idempotency_key"))
        batch_op.create_index(
            op.f("ix_document_sync_logs_idempotency_key"),
            ["idempotency_key"],
            unique=False,
        )
