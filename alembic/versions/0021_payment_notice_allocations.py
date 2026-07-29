"""Link fee receipts to individual payment notices.

Revision ID: 0021_payment_allocations
Revises: 0020_attribution_materials
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import column_names, has_foreign_key, index_names


revision: str = "0021_payment_allocations"
down_revision: str | Sequence[str] | None = "0020_attribution_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    needs_column = "applies_to_event_id" not in column_names(connection, "payment_records")
    needs_foreign_key = not has_foreign_key(
        connection,
        "payment_records",
        ["applies_to_event_id"],
        "legal_events",
    )
    needs_index = "ix_payment_records_applies_to_event_id" not in index_names(connection, "payment_records")
    if needs_column or needs_foreign_key or needs_index:
        with op.batch_alter_table("payment_records") as batch:
            if needs_column:
                batch.add_column(sa.Column("applies_to_event_id", sa.Integer(), nullable=True))
            if needs_foreign_key:
                batch.create_foreign_key(
                    "fk_payment_records_applies_to_event",
                    "legal_events",
                    ["applies_to_event_id"],
                    ["id"],
                )
            if needs_index:
                batch.create_index("ix_payment_records_applies_to_event_id", ["applies_to_event_id"])


def downgrade() -> None:
    with op.batch_alter_table("payment_records") as batch:
        batch.drop_index("ix_payment_records_applies_to_event_id")
        batch.drop_constraint("fk_payment_records_applies_to_event", type_="foreignkey")
        batch.drop_column("applies_to_event_id")
