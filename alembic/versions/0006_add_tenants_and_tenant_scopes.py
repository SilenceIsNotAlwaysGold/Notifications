"""add tenants and tenant scopes

Revision ID: 0006_add_tenants_and_tenant_scopes
Revises: 0005_add_api_key_resource_scopes
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_add_tenants_and_tenant_scopes"
down_revision: Union[str, Sequence[str], None] = "0005_add_api_key_resource_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "legal_cases",
    "group_messages",
    "legal_events",
    "reminders",
    "document_sync_logs",
    "legal_media_files",
    "system_run_logs",
    "case_status_histories",
    "reminder_send_logs",
    "operation_audit_logs",
]


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("contact_name", sa.String(length=128), nullable=True),
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
        sa.Column("contact_email", sa.String(length=128), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_id"), "tenants", ["id"], unique=False)
    op.create_index(op.f("ix_tenants_status"), "tenants", ["status"], unique=False)
    op.create_index(op.f("ix_tenants_tenant_id"), "tenants", ["tenant_id"], unique=True)

    for table_name in TENANT_TABLES:
        op.add_column(table_name, sa.Column("tenant_id", sa.String(length=128), nullable=True))
        op.create_index(op.f(f"ix_{table_name}_tenant_id"), table_name, ["tenant_id"], unique=False)


def downgrade() -> None:
    for table_name in reversed(TENANT_TABLES):
        op.drop_index(op.f(f"ix_{table_name}_tenant_id"), table_name=table_name)
        op.drop_column(table_name, "tenant_id")

    op.drop_index(op.f("ix_tenants_tenant_id"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_status"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_id"), table_name="tenants")
    op.drop_table("tenants")
