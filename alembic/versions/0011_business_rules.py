"""add reminder rules, group features and merchant questions

Revision ID: 0011_business_rules
Revises: 0010_add_ocr_review_workflow
Create Date: 2026-07-20 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_helpers import column_names, has_foreign_key, index_names, table_exists

revision: str = "0011_business_rules"
down_revision: Union[str, Sequence[str], None] = "0010_add_ocr_review_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    if not table_exists(connection, "reminder_rules"):
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

    reminder_columns = column_names(connection, "reminders")
    reminder_indexes = index_names(connection, "reminders")
    missing_reminder_columns = [
        column
        for column in (
            sa.Column("rule_id", sa.Integer(), nullable=True),
            sa.Column("source_event_id", sa.Integer(), nullable=True),
            sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        )
        if column.name not in reminder_columns
    ]
    needs_rule_foreign_key = not has_foreign_key(connection, "reminders", ["rule_id"], "reminder_rules")
    needs_event_foreign_key = not has_foreign_key(connection, "reminders", ["source_event_id"], "legal_events")
    missing_reminder_indexes = [
        (name, columns, unique)
        for name, columns, unique in (
            (op.f("ix_reminders_rule_id"), ["rule_id"], False),
            (op.f("ix_reminders_source_event_id"), ["source_event_id"], False),
            (op.f("ix_reminders_dedupe_key"), ["dedupe_key"], True),
        )
        if name not in reminder_indexes
    ]
    if missing_reminder_columns or needs_rule_foreign_key or needs_event_foreign_key or missing_reminder_indexes:
        with op.batch_alter_table("reminders") as batch_op:
            for column in missing_reminder_columns:
                batch_op.add_column(column)
            if needs_rule_foreign_key:
                batch_op.create_foreign_key("fk_reminders_rule_id", "reminder_rules", ["rule_id"], ["id"])
            if needs_event_foreign_key:
                batch_op.create_foreign_key("fk_reminders_source_event_id", "legal_events", ["source_event_id"], ["id"])
            for name, columns, unique in missing_reminder_indexes:
                batch_op.create_index(name, columns, unique=unique)

    archive_columns = column_names(connection, "wecom_archive_groups")
    missing_archive_columns = [
        column
        for column in (
            sa.Column("group_type", sa.String(length=32), nullable=False, server_default="other"),
            sa.Column("features_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("internal_userids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("alert_userids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("question_timeout_minutes", sa.Integer(), nullable=False, server_default="5"),
        )
        if column.name not in archive_columns
    ]
    archive_index_name = op.f("ix_wecom_archive_groups_group_type")
    needs_archive_index = archive_index_name not in index_names(connection, "wecom_archive_groups")
    if missing_archive_columns or needs_archive_index:
        with op.batch_alter_table("wecom_archive_groups") as batch_op:
            for column in missing_archive_columns:
                batch_op.add_column(column)
            if needs_archive_index:
                batch_op.create_index(archive_index_name, ["group_type"], unique=False)

    if table_exists(connection, "merchant_questions"):
        return
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
