"""add api key resource scopes

Revision ID: 0005_add_api_key_resource_scopes
Revises: 0004_add_audit_auth_fields
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_add_api_key_resource_scopes"
down_revision: Union[str, Sequence[str], None] = "0004_add_audit_auth_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("allowed_group_ids_json", sa.Text(), nullable=True))
    op.add_column("api_keys", sa.Column("allowed_case_ids_json", sa.Text(), nullable=True))
    op.add_column("api_keys", sa.Column("allowed_tenant_ids_json", sa.Text(), nullable=True))
    op.add_column("operation_audit_logs", sa.Column("resource_scope_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("operation_audit_logs", "resource_scope_json")
    op.drop_column("api_keys", "allowed_tenant_ids_json")
    op.drop_column("api_keys", "allowed_case_ids_json")
    op.drop_column("api_keys", "allowed_group_ids_json")
