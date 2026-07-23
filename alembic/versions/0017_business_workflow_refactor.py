"""add case-centric workflow, payments, outbox and reconciliation

Revision ID: 0017_business_workflow_refactor
Revises: 0016_add_wecomapi_room_member_cache
Create Date: 2026-07-24 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017_business_workflow_refactor"
down_revision: Union[str, Sequence[str], None] = "0016_add_wecomapi_room_member_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_indexes(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    with op.batch_alter_table("legal_cases") as batch:
        for column in (
            sa.Column("plaintiff_name", sa.String(255), nullable=True),
            sa.Column("court_name", sa.String(255), nullable=True),
            sa.Column("document_type", sa.String(64), nullable=True),
            sa.Column("filing_date", sa.Date(), nullable=True),
            sa.Column("enforcement_case_no", sa.String(128), nullable=True),
            sa.Column("responsible_contact_id", sa.Integer(), nullable=True),
            sa.Column("lifecycle_stage", sa.String(32), nullable=False, server_default="active"),
            sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("extra_identifiers_json", sa.Text(), nullable=False, server_default="[]"),
        ):
            batch.add_column(column)
        batch.create_index("ix_legal_cases_plaintiff_name", ["plaintiff_name"])
        batch.create_index("ix_legal_cases_enforcement_case_no", ["enforcement_case_no"])
        batch.create_index("ix_legal_cases_responsible_contact_id", ["responsible_contact_id"])
        batch.create_index("ix_legal_cases_lifecycle_stage", ["lifecycle_stage"])

    with op.batch_alter_table("legal_events") as batch:
        for column in (
            sa.Column("attribution_status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("business_status", sa.String(32), nullable=False, server_default="staged"),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("approved_by", sa.String(128), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_reason", sa.Text(), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        ):
            batch.add_column(column)
        batch.create_index("ix_legal_events_attribution_status", ["attribution_status"])
        batch.create_index("ix_legal_events_business_status", ["business_status"])

    with op.batch_alter_table("document_sync_logs") as batch:
        batch.add_column(sa.Column("external_row_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("transport_mode", sa.String(32), nullable=True))
        batch.add_column(sa.Column("mapping_version", sa.String(32), nullable=False, server_default="v2"))
        batch.add_column(sa.Column("outcome", sa.String(32), nullable=False, server_default="failed"))
        batch.add_column(sa.Column("readback_payload_json", sa.Text(), nullable=True))
        batch.create_index("ix_document_sync_logs_transport_mode", ["transport_mode"])
        batch.create_index("ix_document_sync_logs_mapping_version", ["mapping_version"])
        batch.create_index("ix_document_sync_logs_outcome", ["outcome"])

    op.create_table(
        "case_groups",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("legal_cases.id"), nullable=False),
        sa.Column("group_id", sa.String(128), nullable=False), sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confirmed_by", sa.String(128)), sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "group_id", name="uq_case_groups_case_group"),
    )
    _create_indexes("case_groups", ("id", "tenant_id", "case_id", "group_id", "is_primary", "status"))

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)),
        sa.Column("display_name", sa.String(255), nullable=False), sa.Column("role", sa.String(32), nullable=False),
        sa.Column("archive_user_id", sa.String(128)), sa.Column("wecomapi_user_id", sa.String(128)),
        sa.Column("source", sa.String(32), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes("contacts", ("id", "tenant_id", "display_name", "role", "archive_user_id", "wecomapi_user_id", "is_active"))

    op.create_table(
        "contact_groups",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("group_id", sa.String(128), nullable=False), sa.Column("membership_status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contact_id", "group_id", name="uq_contact_groups_contact_group"),
    )
    _create_indexes("contact_groups", ("id", "contact_id", "group_id", "membership_status", "last_seen_at"))
    with op.batch_alter_table("reminders") as batch:
        batch.add_column(sa.Column("target_contact_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_reminders_target_contact", "contacts", ["target_contact_id"], ["id"])
        batch.create_index("ix_reminders_target_contact_id", ["target_contact_id"])

    op.create_table(
        "payment_records",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("legal_cases.id"), nullable=False),
        sa.Column("source_event_id", sa.Integer(), sa.ForeignKey("legal_events.id")),
        sa.Column("source_media_file_id", sa.Integer(), sa.ForeignKey("legal_media_files.id")),
        sa.Column("record_type", sa.String(32), nullable=False), sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("payment_date", sa.Date()), sa.Column("payer_name", sa.String(255)),
        sa.Column("credential_fingerprint", sa.String(128), unique=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reversal_of_id", sa.Integer(), sa.ForeignKey("payment_records.id")), sa.Column("note", sa.Text()),
        sa.Column("approved_by", sa.String(128)), sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(128), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes("payment_records", ("id", "tenant_id", "case_id", "source_event_id", "source_media_file_id", "record_type", "credential_fingerprint", "status", "reversal_of_id"))

    op.create_table(
        "attribution_items",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)), sa.Column("group_id", sa.String(128), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False), sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), sa.ForeignKey("legal_media_files.id")), sa.Column("event_id", sa.Integer(), sa.ForeignKey("legal_events.id")),
        sa.Column("suggested_case_id", sa.Integer(), sa.ForeignKey("legal_cases.id")), sa.Column("assigned_case_id", sa.Integer(), sa.ForeignKey("legal_cases.id")),
        sa.Column("confidence", sa.Integer()), sa.Column("reason", sa.Text()), sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("decided_by", sa.String(128)), sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_type", "subject_id", name="uq_attribution_subject"),
    )
    _create_indexes("attribution_items", ("id", "tenant_id", "group_id", "subject_type", "subject_id", "media_file_id", "event_id", "suggested_case_id", "assigned_case_id", "status"))

    op.create_table(
        "business_outbox",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)),
        sa.Column("task_type", sa.String(64), nullable=False), sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False), sa.Column("dedupe_key", sa.String(255), nullable=False, unique=True),
        sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)), sa.Column("processed_at", sa.DateTime(timezone=True)), sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes("business_outbox", ("id", "tenant_id", "task_type", "aggregate_type", "aggregate_id", "dedupe_key", "status", "available_at"))

    op.create_table(
        "ai_call_audits",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)), sa.Column("media_file_id", sa.Integer()),
        sa.Column("model", sa.String(128)), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("context_message_ids_json", sa.Text(), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Integer()), sa.Column("input_tokens", sa.Integer()), sa.Column("output_tokens", sa.Integer()),
        sa.Column("error_type", sa.String(128)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes("ai_call_audits", ("id", "tenant_id", "media_file_id", "request_hash", "status"))

    op.create_table(
        "kdocs_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("tenant_id", sa.String(128)),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("legal_cases.id")), sa.Column("sync_log_id", sa.Integer(), sa.ForeignKey("document_sync_logs.id")),
        sa.Column("target", sa.String(32), nullable=False), sa.Column("external_row_index", sa.Integer()), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expected_json", sa.Text(), nullable=False), sa.Column("actual_json", sa.Text(), nullable=False),
        sa.Column("differences_json", sa.Text(), nullable=False), sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.String(128)), sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_indexes("kdocs_reconciliations", ("id", "tenant_id", "case_id", "sync_log_id", "target", "status", "checked_at"))

    db = op.get_bind()
    db.execute(sa.text("UPDATE legal_events SET attribution_status=CASE WHEN case_id IS NULL THEN 'pending' ELSE 'confirmed' END"))
    db.execute(sa.text("UPDATE legal_events SET business_status=CASE WHEN case_id IS NULL THEN 'staged' ELSE 'legacy_applied' END"))
    db.execute(sa.text("UPDATE document_sync_logs SET outcome=CASE WHEN response_payload_json LIKE '%\"mock\"%' THEN 'superseded' WHEN response_payload_json LIKE '%\"skipped\"%' THEN 'skipped' WHEN status='success' THEN 'applied' ELSE 'failed' END"))
    db.execute(sa.text("UPDATE document_sync_logs SET transport_mode=CASE WHEN response_payload_json LIKE '%\"mock\"%' THEN 'mock' ELSE 'legacy' END"))
    db.execute(sa.text("INSERT INTO case_groups (tenant_id,case_id,group_id,is_primary,status,source,confirmed_by,confirmed_at,created_at,updated_at) SELECT tenant_id,id,group_id,1,'active','legacy','migration',created_at,created_at,updated_at FROM legal_cases"))
    db.execute(sa.text("INSERT INTO payment_records (tenant_id,case_id,record_type,amount,status,note,approved_by,approved_at,created_by,created_at,updated_at) SELECT tenant_id,id,'opening_balance',paid_amount,'approved','历史已付金额迁移期初余额','migration',updated_at,'migration',updated_at,updated_at FROM legal_cases WHERE paid_amount>0"))
    db.execute(sa.text("INSERT INTO attribution_items (tenant_id,group_id,subject_type,subject_id,media_file_id,evidence_json,status,created_at,updated_at) SELECT tenant_id,group_id,'media',id,id,'{}','pending',created_at,updated_at FROM legal_media_files WHERE case_id IS NULL"))
    db.execute(sa.text("INSERT INTO attribution_items (tenant_id,group_id,subject_type,subject_id,event_id,evidence_json,status,created_at,updated_at) SELECT e.tenant_id,COALESCE(m.group_id,''),'event',e.id,e.id,'{}','pending',e.created_at,e.created_at FROM legal_events e LEFT JOIN group_messages m ON m.id=e.group_message_id WHERE e.case_id IS NULL"))


def downgrade() -> None:
    op.drop_table("kdocs_reconciliations")
    op.drop_table("ai_call_audits")
    op.drop_table("business_outbox")
    op.drop_table("attribution_items")
    op.drop_table("payment_records")
    with op.batch_alter_table("reminders") as batch:
        batch.drop_index("ix_reminders_target_contact_id")
        batch.drop_constraint("fk_reminders_target_contact", type_="foreignkey")
        batch.drop_column("target_contact_id")
    op.drop_table("contact_groups")
    op.drop_table("contacts")
    op.drop_table("case_groups")
    with op.batch_alter_table("document_sync_logs") as batch:
        for name in ("ix_document_sync_logs_outcome", "ix_document_sync_logs_mapping_version", "ix_document_sync_logs_transport_mode"):
            batch.drop_index(name)
        for name in ("readback_payload_json", "outcome", "mapping_version", "transport_mode", "external_row_index"):
            batch.drop_column(name)
    with op.batch_alter_table("legal_events") as batch:
        batch.drop_index("ix_legal_events_business_status")
        batch.drop_index("ix_legal_events_attribution_status")
        for name in ("applied_at", "rejected_reason", "approved_at", "approved_by", "confidence", "business_status", "attribution_status"):
            batch.drop_column(name)
    with op.batch_alter_table("legal_cases") as batch:
        for name in ("ix_legal_cases_lifecycle_stage", "ix_legal_cases_responsible_contact_id", "ix_legal_cases_enforcement_case_no", "ix_legal_cases_plaintiff_name"):
            batch.drop_index(name)
        for name in ("extra_identifiers_json", "source", "lifecycle_stage", "responsible_contact_id", "enforcement_case_no", "filing_date", "document_type", "court_name", "plaintiff_name"):
            batch.drop_column(name)
