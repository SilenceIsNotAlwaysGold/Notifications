"""add tenant settings

Revision ID: 0007_add_tenant_settings
Revises: 0006_add_tenants_and_tenant_scopes
Create Date: 2026-06-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_add_tenant_settings"
down_revision: Union[str, Sequence[str], None] = "0006_add_tenants_and_tenant_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("wecom_send_mode", sa.String(length=32), nullable=True),
        sa.Column("wecom_webhook_url_encrypted", sa.Text(), nullable=True),
        sa.Column("wecom_timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("wecom_max_retry", sa.Integer(), nullable=True),
        sa.Column("tencent_doc_mode", sa.String(length=32), nullable=True),
        sa.Column("tencent_doc_base_url", sa.Text(), nullable=True),
        sa.Column("tencent_doc_access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("tencent_doc_sheet_id", sa.String(length=255), nullable=True),
        sa.Column("tencent_doc_case_sheet_name", sa.String(length=128), nullable=True),
        sa.Column("tencent_doc_archive_sheet_name", sa.String(length=128), nullable=True),
        sa.Column("tencent_doc_case_no_column", sa.String(length=128), nullable=True),
        sa.Column("tencent_doc_status_column", sa.String(length=128), nullable=True),
        sa.Column("tencent_doc_paid_amount_column", sa.String(length=128), nullable=True),
        sa.Column("tencent_doc_timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("ocr_provider", sa.String(length=32), nullable=True),
        sa.Column("ocr_enable_reprocess", sa.Boolean(), nullable=True),
        sa.Column("ocr_max_text_length", sa.Integer(), nullable=True),
        sa.Column("repayment_reminder_days_before", sa.Integer(), nullable=True),
        sa.Column("default_upgrade_days_after_overdue", sa.Integer(), nullable=True),
        sa.Column("case_status_scan_enabled", sa.Boolean(), nullable=True),
        sa.Column("keyword_config_json", sa.Text(), nullable=True),
        sa.Column("feature_flags_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenant_settings_id"), "tenant_settings", ["id"], unique=False)
    op.create_index(op.f("ix_tenant_settings_tenant_id"), "tenant_settings", ["tenant_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenant_settings_tenant_id"), table_name="tenant_settings")
    op.drop_index(op.f("ix_tenant_settings_id"), table_name="tenant_settings")
    op.drop_table("tenant_settings")
