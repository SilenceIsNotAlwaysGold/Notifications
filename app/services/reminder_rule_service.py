from datetime import date, datetime, time, timedelta
from decimal import Decimal
from string import Formatter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.reminder import Reminder
from app.models.reminder_rule import ReminderRule
from app.schemas.legal import ReminderRuleCreate, ReminderRuleUpdate
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import app_timezone, ensure_aware, now_tz

ALLOWED_TEMPLATE_VARIABLES = {
    "case_no",
    "debtor_name",
    "due_date",
    "paid_amount",
    "total_amount",
    "days_overdue",
    "payment_amount",
}

DEFAULT_RULES = [
    *[
        {
            "name": f"还款 D-{offset}",
            "rule_type": "repayment",
            "offset_days": offset,
            "target_role": "debtor",
            "template": "还款提醒：案件 {case_no} 将于 {due_date} 到期，已还 {paid_amount}/{total_amount}，请及时安排还款。",
        }
        for offset in (7, 3, 1, 0)
    ],
    *[
        {
            "name": f"违约 D+{offset}",
            "rule_type": "default_upgrade",
            "offset_days": offset,
            "target_role": "lawyer",
            "template": "案件 {case_no} 已逾期 {days_overdue} 天，请跟进强制执行 / 仲裁。",
        }
        for offset in (1, 3, 7)
    ],
    *[
        {
            "name": f"缴费 D+{offset}",
            "rule_type": "payment_tracking",
            "offset_days": offset,
            "target_role": "lawyer",
            "template": "缴费跟踪：案件 {case_no} 待缴金额 {payment_amount}，请确认是否已完成缴费。",
        }
        for offset in range(7)
    ],
]


class ReminderRuleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def ensure_default_rules(self) -> list[ReminderRule]:
        existing = list(
            self.db.scalars(
                select(ReminderRule)
                .where(ReminderRule.tenant_id.is_(None))
                .order_by(ReminderRule.sort_order.asc(), ReminderRule.id.asc())
            ).all()
        )
        if existing:
            return existing
        for index, definition in enumerate(DEFAULT_RULES):
            self.db.add(
                ReminderRule(
                    tenant_id=None,
                    send_time="09:00",
                    sort_order=index,
                    enabled=True,
                    **definition,
                )
            )
        self.db.flush()
        return list(
            self.db.scalars(
                select(ReminderRule)
                .where(ReminderRule.tenant_id.is_(None))
                .order_by(ReminderRule.sort_order.asc(), ReminderRule.id.asc())
            ).all()
        )

    def list_rules(self, tenant_id: str | None = None, rule_type: str | None = None) -> list[ReminderRule]:
        self.ensure_default_rules()
        query = select(ReminderRule)
        if tenant_id is not None:
            query = query.where((ReminderRule.tenant_id == tenant_id) | (ReminderRule.tenant_id.is_(None)))
        if rule_type:
            query = query.where(ReminderRule.rule_type == rule_type)
        return list(self.db.scalars(query.order_by(ReminderRule.sort_order.asc(), ReminderRule.id.asc())).all())

    def create_rule(self, payload: ReminderRuleCreate) -> ReminderRule:
        self.validate_template(payload.template)
        rule = ReminderRule(**payload.model_dump())
        self.db.add(rule)
        self.db.flush()
        return rule

    def update_rule(self, rule_id: int, payload: ReminderRuleUpdate) -> tuple[ReminderRule, int]:
        rule = self.db.get(ReminderRule, rule_id)
        if not rule:
            raise ValueError("提醒规则不存在")
        values = payload.model_dump(exclude_unset=True)
        if "template" in values:
            self.validate_template(values["template"])
        for field, value in values.items():
            setattr(rule, field, value)
        rule.updated_at = now_tz()
        self.db.flush()
        rebuilt = self.rebuild_pending_for_rule(rule)
        return rule, rebuilt

    def effective_rules(self, tenant_id: str | None, rule_type: str) -> list[ReminderRule]:
        self.ensure_default_rules()
        tenant_rules: list[ReminderRule] = []
        if tenant_id:
            tenant_rules = list(
                self.db.scalars(
                    select(ReminderRule)
                    .where(ReminderRule.tenant_id == tenant_id)
                    .where(ReminderRule.rule_type == rule_type)
                    .order_by(ReminderRule.sort_order.asc(), ReminderRule.id.asc())
                ).all()
            )
        rules = tenant_rules or list(
            self.db.scalars(
                select(ReminderRule)
                .where(ReminderRule.tenant_id.is_(None))
                .where(ReminderRule.rule_type == rule_type)
                .order_by(ReminderRule.sort_order.asc(), ReminderRule.id.asc())
            ).all()
        )
        return [rule for rule in rules if rule.enabled]

    def create_case_rules_for_date(
        self,
        legal_case: LegalCase,
        rule_type: str,
        reference_date: date,
        scan_date: date,
        source_event: LegalEvent | None = None,
        payment_amount: Any = None,
    ) -> list[Reminder]:
        if not WeComArchiveGroupService(self.db).feature_enabled(legal_case.group_id, "case_reminders"):
            return []
        created: list[Reminder] = []
        for rule in self.effective_rules(legal_case.tenant_id, rule_type):
            target_date = self._target_date(rule, reference_date)
            if target_date != scan_date:
                continue
            created.extend(self._create_for_rule(rule, legal_case, target_date, source_event, payment_amount))
        return created

    def create_payment_tracking(
        self,
        legal_case: LegalCase,
        start_date: date,
        source_event: LegalEvent | None = None,
        payment_amount: Any = None,
    ) -> list[Reminder]:
        if not WeComArchiveGroupService(self.db).feature_enabled(legal_case.group_id, "payment_tracking"):
            return []
        created: list[Reminder] = []
        for rule in self.effective_rules(legal_case.tenant_id, "payment_tracking"):
            target_date = self._target_date(rule, start_date)
            created.extend(self._create_for_rule(rule, legal_case, target_date, source_event, payment_amount))
        return created

    def rebuild_pending_for_rule(self, rule: ReminderRule) -> int:
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.rule_id == rule.id)
                .where(Reminder.status == "pending")
                .order_by(Reminder.id.asc())
            ).all()
        )
        changed = 0
        for reminder in reminders:
            if not rule.enabled:
                reminder.status = "cancelled"
                reminder.cancelled_at = now_tz()
                reminder.cancel_reason = f"提醒规则 {rule.name} 已停用"
                changed += 1
                continue
            legal_case = self.db.get(LegalCase, reminder.case_id) if reminder.case_id else None
            if not legal_case:
                continue
            source_event = self.db.get(LegalEvent, reminder.source_event_id) if reminder.source_event_id else None
            reference_date = self._reference_date(rule, legal_case, source_event)
            if reference_date is None:
                continue
            reminder.remind_at = self._at_send_time(self._target_date(rule, reference_date), rule.send_time)
            reminder.content = self.render_template(rule.template, legal_case, source_event.amount if source_event else None)
            reminder.target_userid = self._targets(rule.target_role, legal_case)[0]
            reminder.cancelled_at = None
            reminder.cancel_reason = None
            changed += 1
        self.db.flush()
        return changed

    def _create_for_rule(
        self,
        rule: ReminderRule,
        legal_case: LegalCase,
        target_date: date,
        source_event: LegalEvent | None,
        payment_amount: Any,
    ) -> list[Reminder]:
        reminders: list[Reminder] = []
        targets = self._targets(rule.target_role, legal_case)
        for target_index, target_userid in enumerate(targets):
            source_key = f"event:{source_event.id}" if source_event else f"case:{legal_case.id}"
            dedupe_key = f"rule:{rule.id}:{source_key}:{target_date.isoformat()}:{target_index}"
            if self.db.scalar(select(Reminder.id).where(Reminder.dedupe_key == dedupe_key)):
                continue
            reminder = Reminder(
                case_id=legal_case.id,
                tenant_id=legal_case.tenant_id,
                group_id=legal_case.group_id,
                reminder_type=self._reminder_type(rule.rule_type),
                remind_at=self._at_send_time(target_date, rule.send_time),
                content=self.render_template(rule.template, legal_case, payment_amount),
                target_userid=target_userid,
                rule_id=rule.id,
                source_event_id=source_event.id if source_event else None,
                dedupe_key=dedupe_key,
                status="pending",
            )
            self.db.add(reminder)
            reminders.append(reminder)
        self.db.flush()
        return reminders

    @staticmethod
    def validate_template(template: str) -> None:
        try:
            variables = {name for _, name, _, _ in Formatter().parse(template) if name}
        except ValueError as exc:
            raise ValueError("提醒模板格式错误") from exc
        unsupported = variables - ALLOWED_TEMPLATE_VARIABLES
        if unsupported:
            raise ValueError(f"提醒模板包含不支持的变量：{', '.join(sorted(unsupported))}")

    @staticmethod
    def render_template(template: str, legal_case: LegalCase, payment_amount: Any = None) -> str:
        total = legal_case.total_amount or Decimal("0.00")
        paid = legal_case.paid_amount or Decimal("0.00")
        days_overdue = max(0, (now_tz().date() - legal_case.due_date).days)
        values = {
            "case_no": legal_case.case_no,
            "debtor_name": legal_case.debtor_name,
            "due_date": legal_case.due_date.isoformat(),
            "paid_amount": str(paid),
            "total_amount": str(total),
            "days_overdue": days_overdue,
            "payment_amount": str(payment_amount) if payment_amount is not None else "待确认",
        }
        return template.format_map(values)

    @staticmethod
    def _target_date(rule: ReminderRule, reference_date: date) -> date:
        if rule.rule_type == "repayment":
            return reference_date - timedelta(days=rule.offset_days)
        return reference_date + timedelta(days=rule.offset_days)

    @staticmethod
    def _at_send_time(target_date: date, send_time: str) -> datetime:
        hour, minute = [int(value) for value in send_time.split(":", 1)]
        return datetime.combine(target_date, time(hour, minute), tzinfo=app_timezone())

    @staticmethod
    def _targets(target_role: str, legal_case: LegalCase) -> list[str | None]:
        if target_role == "debtor":
            return [legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid]
        if target_role == "both":
            values = [legal_case.debtor_wecom_userid, legal_case.lawyer_wecom_userid]
            unique = list(dict.fromkeys(value for value in values if value))
            return unique or [None]
        return [legal_case.lawyer_wecom_userid]

    @staticmethod
    def _reminder_type(rule_type: str) -> str:
        return "repayment_before_due" if rule_type == "repayment" else rule_type

    @staticmethod
    def _reference_date(rule: ReminderRule, legal_case: LegalCase, source_event: LegalEvent | None) -> date | None:
        if rule.rule_type == "repayment":
            return legal_case.due_date
        if rule.rule_type == "default_upgrade":
            return ensure_aware(legal_case.overdue_at).date() if legal_case.overdue_at else None
        return ensure_aware(source_event.event_time).date() if source_event and source_event.event_time else None
