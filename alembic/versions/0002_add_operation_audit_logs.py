"""add operation audit logs

Revision ID: 0002_add_operation_audit_logs
Revises: 0001_initial_schema
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_operation_audit_logs"
down_revision: Union[str, Sequence[str], None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operation_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=128), nullable=True),
        sa.Column("auth_type", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("request_summary_json", sa.Text(), nullable=True),
        sa.Column("response_summary_json", sa.Text(), nullable=True),
        sa.Column("client_host", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operation_audit_logs_action"), "operation_audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_operation_audit_logs_created_at"), "operation_audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_operation_audit_logs_operator"), "operation_audit_logs", ["operator"], unique=False)
    op.create_index(op.f("ix_operation_audit_logs_path"), "operation_audit_logs", ["path"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_operation_audit_logs_path"), table_name="operation_audit_logs")
    op.drop_index(op.f("ix_operation_audit_logs_operator"), table_name="operation_audit_logs")
    op.drop_index(op.f("ix_operation_audit_logs_created_at"), table_name="operation_audit_logs")
    op.drop_index(op.f("ix_operation_audit_logs_action"), table_name="operation_audit_logs")
    op.drop_table("operation_audit_logs")
