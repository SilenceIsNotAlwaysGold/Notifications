"""align reminder defaults and add group onboarding policy

Revision ID: 0019_business_spec_defaults
Revises: 0018_kdocs_row_metadata
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0019_business_spec_defaults"
down_revision: Union[str, Sequence[str], None] = "0018_kdocs_row_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("wecom_archive_groups") as batch_op:
        batch_op.add_column(sa.Column("access_policy", sa.String(length=32), nullable=False, server_default="auto"))
        batch_op.create_index("ix_wecom_archive_groups_access_policy", ["access_policy"], unique=False)

    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE wecom_archive_groups SET access_policy='blacklist' WHERE status='disabled'")
    )
    connection.execute(
        sa.text(
            "UPDATE wecom_archive_groups SET status='enabled', group_type='merchant' "
            "WHERE access_policy='auto' AND display_name LIKE '%法务起诉沟通群%'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE wecom_archive_groups SET status='enabled', group_type='debtor' "
            "WHERE access_policy='auto' AND display_name LIKE '%还款对接群%'"
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM reminder_rules WHERE tenant_id IS NULL AND rule_type='payment_tracking' "
            "AND send_time='09:00' AND target_role='lawyer' AND "
            "template=:legacy_template AND ((name='缴费 D+0' AND offset_days=0) OR "
            "(name='缴费 D+1' AND offset_days=1) OR (name='缴费 D+2' AND offset_days=2) OR "
            "(name='缴费 D+3' AND offset_days=3) OR (name='缴费 D+4' AND offset_days=4) OR "
            "(name='缴费 D+5' AND offset_days=5) OR (name='缴费 D+6' AND offset_days=6))"
        ),
        {
            "legacy_template": "缴费跟踪：案件 {case_no} 待缴金额 {payment_amount}，请确认是否已完成缴费。"
        },
    )
    defaults = [
        ("缴费 D+3", "payment_tracking", 3, "lawyer", "缴费跟踪：案件 {case_no} 待缴金额 {payment_amount}，请确认是否已完成缴费。", 7),
        ("缴费 D+5", "payment_tracking", 5, "lawyer", "缴费跟踪：案件 {case_no} 待缴金额 {payment_amount}，请确认是否已完成缴费。", 8),
        ("缴费 D+7", "payment_tracking", 7, "both", "缴费跟踪：案件 {case_no} 待缴金额 {payment_amount}，已到缴费期限，请升级处理。", 9),
        ("开庭方式确认 D-5", "court_mode_confirmation", 5, "lawyer", "开庭方式确认：案件 {case_no} 即将开庭，请确认线上或现场并补充安排。", 10),
        ("开庭提醒 D-3", "court_reminder", 3, "lawyer", "开庭提醒：案件 {case_no} 即将开庭，请核对法院、时间、代理人和材料。", 11),
        ("开庭提醒 D-1", "court_reminder", 1, "lawyer", "开庭提醒：案件 {case_no} 即将开庭，请核对法院、时间、代理人和材料。", 12),
    ]
    for name, rule_type, offset, role, template, order in defaults:
        connection.execute(
            sa.text(
                "INSERT INTO reminder_rules "
                "(tenant_id,name,rule_type,offset_days,send_time,target_role,template,sort_order,enabled,created_at,updated_at) "
                "SELECT NULL,:name,:rule_type,:offset,'09:00',:role,:template,:sort_order,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM reminder_rules WHERE tenant_id IS NULL AND name=:name)"
            ),
            {"name": name, "rule_type": rule_type, "offset": offset, "role": role, "template": template, "sort_order": order},
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM reminder_rules WHERE tenant_id IS NULL AND rule_type IN ('court_mode_confirmation','court_reminder')"))
    with op.batch_alter_table("wecom_archive_groups") as batch_op:
        batch_op.drop_index("ix_wecom_archive_groups_access_policy")
        batch_op.drop_column("access_policy")
