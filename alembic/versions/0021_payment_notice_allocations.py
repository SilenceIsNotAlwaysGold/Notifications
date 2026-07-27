"""Link fee receipts to individual payment notices.

Revision ID: 0021_payment_allocations
Revises: 0020_attribution_materials
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_payment_allocations"
down_revision: str | Sequence[str] | None = "0020_attribution_materials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("payment_records") as batch:
        batch.add_column(sa.Column("applies_to_event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_payment_records_applies_to_event",
            "legal_events",
            ["applies_to_event_id"],
            ["id"],
        )
        batch.create_index("ix_payment_records_applies_to_event_id", ["applies_to_event_id"])


def downgrade() -> None:
    with op.batch_alter_table("payment_records") as batch:
        batch.drop_index("ix_payment_records_applies_to_event_id")
        batch.drop_constraint("fk_payment_records_applies_to_event", type_="foreignkey")
        batch.drop_column("applies_to_event_id")
