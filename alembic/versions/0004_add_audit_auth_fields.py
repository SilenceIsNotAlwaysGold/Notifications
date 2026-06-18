"""add audit auth fields

Revision ID: 0004_add_audit_auth_fields
Revises: 0003_add_api_keys
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_add_audit_auth_fields"
down_revision: Union[str, Sequence[str], None] = "0003_add_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("operation_audit_logs", sa.Column("operator_role", sa.String(length=32), nullable=True))
    op.add_column("operation_audit_logs", sa.Column("api_key_id", sa.Integer(), nullable=True))
    op.add_column("operation_audit_logs", sa.Column("api_key_prefix", sa.String(length=16), nullable=True))
    op.create_index(op.f("ix_operation_audit_logs_operator_role"), "operation_audit_logs", ["operator_role"], unique=False)
    op.create_index(op.f("ix_operation_audit_logs_api_key_id"), "operation_audit_logs", ["api_key_id"], unique=False)
    op.create_index(op.f("ix_operation_audit_logs_api_key_prefix"), "operation_audit_logs", ["api_key_prefix"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_operation_audit_logs_api_key_prefix"), table_name="operation_audit_logs")
    op.drop_index(op.f("ix_operation_audit_logs_api_key_id"), table_name="operation_audit_logs")
    op.drop_index(op.f("ix_operation_audit_logs_operator_role"), table_name="operation_audit_logs")
    op.drop_column("operation_audit_logs", "api_key_prefix")
    op.drop_column("operation_audit_logs", "api_key_id")
    op.drop_column("operation_audit_logs", "operator_role")
