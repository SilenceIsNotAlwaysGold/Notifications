"""add reminder rules, group features and merchant questions

Revision ID: 0011_business_rules
Revises: 0010_add_ocr_review_workflow
Create Date: 2026-07-20 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_business_rules"
down_revision: Union[str, Sequence[str], None] = "0010_add_ocr_review_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminder_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rule_type", sa.String(length=64), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("send_time", sa.String(length=5), nullable=False),
        sa.Column("target_role", sa.String(length=32), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_reminder_rules_tenant_name"),
    )
    op.create_index(op.f("ix_reminder_rules_id"), "reminder_rules", ["id"], unique=False)
    op.create_index(op.f("ix_reminder_rules_tenant_id"), "reminder_rules", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_reminder_rules_rule_type"), "reminder_rules", ["rule_type"], unique=False)
    op.create_index(op.f("ix_reminder_rules_enabled"), "reminder_rules", ["enabled"], unique=False)

    with op.batch_alter_table("reminders") as batch_op:
        batch_op.add_column(sa.Column("rule_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_event_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("dedupe_key", sa.String(length=255), nullable=True))
        batch_op.create_foreign_key("fk_reminders_rule_id", "reminder_rules", ["rule_id"], ["id"])
        batch_op.create_foreign_key("fk_reminders_source_event_id", "legal_events", ["source_event_id"], ["id"])
        batch_op.create_index(op.f("ix_reminders_rule_id"), ["rule_id"], unique=False)
        batch_op.create_index(op.f("ix_reminders_source_event_id"), ["source_event_id"], unique=False)
        batch_op.create_index(op.f("ix_reminders_dedupe_key"), ["dedupe_key"], unique=True)

    with op.batch_alter_table("wecom_archive_groups") as batch_op:
        batch_op.add_column(sa.Column("group_type", sa.String(length=32), nullable=False, server_default="other"))
        batch_op.add_column(sa.Column("features_json", sa.Text(), nullable=False, server_default="{}"))
        batch_op.add_column(sa.Column("internal_userids_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("alert_userids_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("question_timeout_minutes", sa.Integer(), nullable=False, server_default="5"))
        batch_op.create_index(op.f("ix_wecom_archive_groups_group_type"), ["group_type"], unique=False)

    op.create_table(
        "merchant_questions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("group_message_id", sa.Integer(), nullable=False),
        sa.Column("sender_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reply_message_id", sa.Integer(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_id", sa.Integer(), nullable=True),
        sa.Column("assigned_userid", sa.String(length=128), nullable=True),
        sa.Column("closed_by", sa.String(length=128), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_message_id"], ["group_messages.id"]),
        sa.ForeignKeyConstraint(["reply_message_id"], ["group_messages.id"]),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_merchant_questions_id"), "merchant_questions", ["id"], unique=False)
    op.create_index(op.f("ix_merchant_questions_tenant_id"), "merchant_questions", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_merchant_questions_group_id"), "merchant_questions", ["group_id"], unique=False)
    op.create_index(op.f("ix_merchant_questions_group_message_id"), "merchant_questions", ["group_message_id"], unique=True)
    op.create_index(op.f("ix_merchant_questions_sender_id"), "merchant_questions", ["sender_id"], unique=False)
    op.create_index(op.f("ix_merchant_questions_asked_at"), "merchant_questions", ["asked_at"], unique=False)
    op.create_index(op.f("ix_merchant_questions_deadline_at"), "merchant_questions", ["deadline_at"], unique=False)
    op.create_index(op.f("ix_merchant_questions_status"), "merchant_questions", ["status"], unique=False)
    op.create_index(op.f("ix_merchant_questions_reminder_id"), "merchant_questions", ["reminder_id"], unique=False)


def downgrade() -> None:
    op.drop_table("merchant_questions")
    with op.batch_alter_table("wecom_archive_groups") as batch_op:
        batch_op.drop_index(op.f("ix_wecom_archive_groups_group_type"))
        batch_op.drop_column("question_timeout_minutes")
        batch_op.drop_column("alert_userids_json")
        batch_op.drop_column("internal_userids_json")
        batch_op.drop_column("features_json")
        batch_op.drop_column("group_type")
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_index(op.f("ix_reminders_dedupe_key"))
        batch_op.drop_index(op.f("ix_reminders_source_event_id"))
        batch_op.drop_index(op.f("ix_reminders_rule_id"))
        batch_op.drop_constraint("fk_reminders_source_event_id", type_="foreignkey")
        batch_op.drop_constraint("fk_reminders_rule_id", type_="foreignkey")
        batch_op.drop_column("dedupe_key")
        batch_op.drop_column("source_event_id")
        batch_op.drop_column("rule_id")
    op.drop_table("reminder_rules")
