import logging
import json
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.wecom_message import WeComMessageAdapter
from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.reminder import Reminder
from app.models.reminder_send_log import ReminderSendLog
from app.services.reminder_rule_service import ReminderRuleService
from app.services.system_run_log_service import SystemRunLogService
from app.services.tenant_settings_service import TenantSettingsService
from app.utils.datetime_utils import app_timezone, ensure_aware, now_tz, start_of_day

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, db: Session, wecom_adapter: WeComMessageAdapter | None = None) -> None:
        self.db = db
        self.wecom_adapter = wecom_adapter or WeComMessageAdapter()

    def create_repayment_reminder(self, case_id: int, days_before: int) -> Reminder:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
        target_date = legal_case.due_date - timedelta(days=days_before)
        rule_reminders = ReminderRuleService(self.db).create_case_rules_for_date(
            legal_case,
            "repayment",
            legal_case.due_date,
            target_date,
        )
        if rule_reminders:
            return rule_reminders[0]
        remind_at = datetime.combine(target_date, datetime.min.time(), tzinfo=app_timezone()).replace(hour=9)
        existing = self._find_existing_same_day(legal_case.id, "repayment_before_due", remind_at)
        if existing:
            return existing
        content = f"还款提醒：案件 {legal_case.case_no} 将于 {legal_case.due_date} 到期，请及时跟进还款。"
        return self._create(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            group_id=legal_case.group_id,
            reminder_type="repayment_before_due",
            remind_at=remind_at,
            content=content,
            target_userid=legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid,
        )

    def create_custom_reminder(
        self,
        group_id: str,
        remind_at: datetime,
        content: str,
        target_userid: str | None = None,
        case_id: int | None = None,
        tenant_id: str | None = None,
    ) -> Reminder:
        legal_case = self.db.get(LegalCase, case_id) if case_id is not None else None
        if legal_case:
            tenant_id = tenant_id or legal_case.tenant_id
        if tenant_id is None:
            tenant_id = self._infer_tenant_id_from_group(group_id)
        return self._create(
            case_id=case_id,
            tenant_id=tenant_id,
            group_id=group_id,
            reminder_type="custom",
            remind_at=ensure_aware(remind_at),
            content=content,
            target_userid=target_userid,
        )

    def update_custom_reminder(
        self,
        reminder: Reminder,
        remind_at: datetime | None = None,
        content: str | None = None,
        target_userid: str | None = None,
        fields_set: set[str] | None = None,
    ) -> Reminder:
        if reminder.reminder_type != "custom":
            raise ValueError("仅自定义提醒可以编辑")
        if reminder.status != "pending":
            raise ValueError("仅待发送提醒可以编辑")
        fields = fields_set or set()
        if "remind_at" in fields and remind_at is not None:
            reminder.remind_at = ensure_aware(remind_at)
        if "content" in fields and content is not None:
            reminder.content = content.strip()
        if "target_userid" in fields:
            reminder.target_userid = target_userid.strip() if target_userid else None
        self.db.flush()
        return reminder

    def cancel_reminder(self, reminder: Reminder, reason: str, operator: str | None = None) -> Reminder:
        if reminder.status != "pending":
            raise ValueError("仅待发送提醒可以取消")
        reminder.status = "cancelled"
        reminder.cancelled_at = now_tz()
        reminder.cancel_reason = f"{reason.strip()}（操作人：{operator}）" if operator else reason.strip()
        self.db.flush()
        return reminder

    def create_default_upgrade_reminder(self, case_id: int, scan_date: date | None = None) -> Reminder:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
        reference_date = ensure_aware(legal_case.overdue_at).date() if legal_case.overdue_at else legal_case.due_date
        target_date = scan_date or now_tz().date()
        rule_reminders = ReminderRuleService(self.db).create_case_rules_for_date(
            legal_case,
            "default_upgrade",
            reference_date,
            target_date,
        )
        if rule_reminders:
            return rule_reminders[0]
        remind_at = now_tz()
        existing = self._find_existing_same_day(legal_case.id, "default_upgrade", remind_at)
        if existing:
            return existing
        content = "该案已逾期 3 天，请申请强制执行 / 仲裁。"
        return self._create(
            case_id=legal_case.id,
            tenant_id=legal_case.tenant_id,
            group_id=legal_case.group_id,
            reminder_type="default_upgrade",
            remind_at=remind_at,
            content=content,
            target_userid=legal_case.lawyer_wecom_userid,
        )

    def create_payment_tracking(
        self,
        case_id: int | None,
        start_date: date,
        days: int = 7,
        source_event_id: int | None = None,
        payment_amount: object = None,
    ) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id) if case_id else None
        if case_id and not legal_case:
            raise ValueError("案件不存在")
        if not legal_case:
            return []

        source_event = self.db.get(LegalEvent, source_event_id) if source_event_id else None
        return ReminderRuleService(self.db).create_payment_tracking(
            legal_case,
            start_date,
            source_event=source_event,
            payment_amount=payment_amount,
        )

    def create_court_reminders(
        self,
        case_id: int,
        court_time: datetime | str | None,
        source_event_id: int | None = None,
    ) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case or not court_time:
            return []
        if isinstance(court_time, str):
            try:
                court_time = datetime.fromisoformat(court_time)
            except ValueError:
                return []
        source_event = self.db.get(LegalEvent, source_event_id) if source_event_id else None
        service = ReminderRuleService(self.db)
        created: list[Reminder] = []
        for rule_type in ("court_mode_confirmation", "court_reminder"):
            for rule in service.effective_rules(legal_case.tenant_id, rule_type):
                target_date = court_time.date() - timedelta(days=rule.offset_days)
                created.extend(service.create_rule_reminders(rule, legal_case, target_date, source_event))
        return created

    def create_installment_reminders(
        self,
        case_id: int,
        installments: list[dict[str, object]],
        source_event_id: int | None = None,
    ) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            return []
        created: list[Reminder] = []
        for index, installment in enumerate(installments[:120], start=1):
            try:
                due_date = date.fromisoformat(str(installment.get("due_date") or "")[:10])
            except ValueError:
                continue
            sequence = installment.get("sequence") or index
            amount = installment.get("amount") or "待确认"
            for label, delta_days, target_userid in (
                ("d-7", -7, legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid),
                ("d0", 0, legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid),
                ("d+3", 3, legal_case.lawyer_wecom_userid),
            ):
                target_date = due_date + timedelta(days=delta_days)
                dedupe_key = f"installment:{source_event_id or 0}:{case_id}:{sequence}:{label}"
                if self.db.scalar(select(Reminder.id).where(Reminder.dedupe_key == dedupe_key)):
                    continue
                created.append(
                    self._create(
                        case_id=case_id,
                        tenant_id=legal_case.tenant_id,
                        group_id=legal_case.group_id,
                        reminder_type="installment_repayment",
                        remind_at=datetime.combine(target_date, datetime.min.time(), tzinfo=app_timezone()).replace(hour=9),
                        content=f"第 {sequence} 期还款提醒：案件 {legal_case.case_no} 应于 {due_date.isoformat()} 还款 {amount} 元。",
                        target_userid=target_userid,
                        source_event_id=source_event_id,
                        dedupe_key=dedupe_key,
                    )
                )
        return created

    def cancel_pending_case_reminders(self, case_id: int, reason: str) -> int:
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.case_id == case_id)
                .where(Reminder.status == "pending")
                .where(
                    Reminder.reminder_type.in_(
                        ("repayment_before_due", "installment_repayment", "default_upgrade")
                    )
                )
            ).all()
        )
        for reminder in reminders:
            reminder.status = "cancelled"
            reminder.cancelled_at = now_tz()
            reminder.cancel_reason = reason
        self.db.flush()
        return len(reminders)

    def create_repayment_rules_for_date(self, case_id: int, scan_date: date) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
        return ReminderRuleService(self.db).create_case_rules_for_date(
            legal_case,
            "repayment",
            legal_case.due_date,
            scan_date,
        )

    def create_default_rules_for_date(self, case_id: int, scan_date: date) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case or not legal_case.overdue_at:
            return []
        return ReminderRuleService(self.db).create_case_rules_for_date(
            legal_case,
            "default_upgrade",
            ensure_aware(legal_case.overdue_at).date(),
            scan_date,
        )

    def cancel_pending_payment_tracking(self, case_id: int, reason: str) -> int:
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.case_id == case_id)
                .where(Reminder.reminder_type == "payment_tracking")
                .where(Reminder.status == "pending")
            ).all()
        )
        cancelled_at = now_tz()
        for reminder in reminders:
            reminder.status = "cancelled"
            reminder.cancelled_at = cancelled_at
            reminder.cancel_reason = reason
        self.db.flush()
        return len(reminders)

    def send_due_reminders(self, trigger_type: str = "system", operator: str | None = None) -> dict[str, object]:
        run_service = SystemRunLogService(self.db)
        run_log = run_service.start_run("reminder_send", trigger_type, summary={"operator": operator} if operator else None)
        due_reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.status == "pending")
                .where(Reminder.remind_at <= now_tz())
                .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
            ).all()
        )
        sent = 0
        simulated = 0
        failed = 0
        retrying = 0
        try:
            for reminder in due_reminders:
                mentioned = [reminder.target_userid] if reminder.target_userid else None
                attempt_no = reminder.retry_count + 1
                result = None
                try:
                    result = self._send_text(reminder, mentioned)
                    self._write_send_log(reminder, result, mentioned, None, attempt_no)
                    if not result.get("success"):
                        raise RuntimeError(result.get("error") or "企业微信发送失败")
                    if result.get("mode") == "mock":
                        self.mark_simulated(reminder)
                        simulated += 1
                    else:
                        self.mark_sent(reminder)
                        sent += 1
                except Exception as exc:
                    logger.exception("发送提醒失败，reminder_id=%s", reminder.id)
                    if result is None or result.get("success"):
                        result = {
                            "success": False,
                            "mode": getattr(self.wecom_adapter, "mode", "mock"),
                            "status_code": None,
                            "response": None,
                            "error": str(exc),
                        }
                        self._write_send_log(reminder, result, mentioned, None, attempt_no)
                    if self.mark_send_failure(reminder, str(exc)):
                        failed += 1
                    else:
                        retrying += 1
            summary = {"sent": sent, "simulated": simulated, "failed": failed, "retrying": retrying, "total": len(due_reminders), **({"operator": operator} if operator else {})}
            if failed:
                run_service.finish_partial(run_log, summary=summary, total_count=len(due_reminders), success_count=sent + simulated, failed_count=failed)
            else:
                run_service.finish_success(run_log, summary=summary, total_count=len(due_reminders), success_count=sent + simulated, failed_count=failed)
        except Exception as exc:
            run_service.finish_failed(
                run_log,
                str(exc),
                summary={"sent": sent, "simulated": simulated, "failed": failed, "retrying": retrying, "total": len(due_reminders), **({"operator": operator} if operator else {})},
            )
            raise
        self.db.flush()
        return {"sent": sent, "simulated": simulated, "failed": failed, "retrying": retrying, "total": len(due_reminders)}

    def list_reminders(
        self,
        status: str | None = None,
        reminder_type: str | None = None,
        group_id: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[int, list[Reminder]]:
        query = select(Reminder)
        if status:
            query = query.where(Reminder.status == status)
        if reminder_type:
            query = query.where(Reminder.reminder_type == reminder_type)
        if group_id:
            query = query.where(Reminder.group_id == group_id)
        all_items = list(self.db.scalars(query.order_by(Reminder.id.desc())).all())
        return len(all_items), all_items[offset : offset + limit]

    def mark_sent(self, reminder: Reminder) -> None:
        reminder.status = "sent"
        reminder.last_error = None
        reminder.sent_at = now_tz()

    def mark_simulated(self, reminder: Reminder) -> None:
        reminder.status = "simulated"
        reminder.last_error = None
        reminder.sent_at = None

    def mark_failed(self, reminder: Reminder, error: str) -> None:
        reminder.status = "failed"
        reminder.retry_count += 1
        reminder.last_error = error

    def mark_send_failure(self, reminder: Reminder, error: str) -> bool:
        reminder.retry_count += 1
        reminder.last_error = error
        max_retry = self._max_retry_for_tenant(reminder.tenant_id)
        if reminder.retry_count >= max_retry:
            reminder.status = "failed"
            return True
        reminder.status = "pending"
        return False

    def _create(
        self,
        case_id: int | None,
        tenant_id: str | None,
        group_id: str,
        reminder_type: str,
        remind_at: datetime,
        content: str,
        target_userid: str | None = None,
        rule_id: int | None = None,
        source_event_id: int | None = None,
        dedupe_key: str | None = None,
        flush: bool = True,
    ) -> Reminder:
        reminder = Reminder(
            case_id=case_id,
            tenant_id=tenant_id,
            group_id=group_id,
            reminder_type=reminder_type,
            remind_at=ensure_aware(remind_at),
            content=content,
            target_userid=target_userid,
            rule_id=rule_id,
            source_event_id=source_event_id,
            dedupe_key=dedupe_key,
            status="pending",
        )
        self.db.add(reminder)
        if flush:
            self.db.flush()
        return reminder

    def _find_existing_same_day(self, case_id: int, reminder_type: str, remind_at: datetime) -> Reminder | None:
        day_start = start_of_day(remind_at.date())
        next_day = day_start + timedelta(days=1)
        return self.db.scalar(
            select(Reminder)
            .where(Reminder.case_id == case_id)
            .where(Reminder.reminder_type == reminder_type)
            .where(Reminder.remind_at >= day_start)
            .where(Reminder.remind_at < next_day)
        )

    @staticmethod
    def _default_today_remind_at() -> datetime:
        now = now_tz()
        nine_am = datetime(now.year, now.month, now.day, 9, 0, tzinfo=app_timezone())
        return now if now >= nine_am else nine_am

    def _write_send_log(
        self,
        reminder: Reminder,
        result: dict[str, object],
        mentioned_userids: list[str] | None,
        mentioned_mobiles: list[str] | None,
        attempt_no: int,
    ) -> None:
        request_payload = {
            "group_id": reminder.group_id,
            "content": reminder.content[:200],
            "mentioned_userids": mentioned_userids or [],
            "mentioned_mobiles": mentioned_mobiles or [],
        }
        log = ReminderSendLog(
            reminder_id=reminder.id,
            tenant_id=reminder.tenant_id,
            group_id=reminder.group_id,
            target_userid=reminder.target_userid,
            send_mode=str(result.get("mode") or getattr(self.wecom_adapter, "mode", "mock")),
            status="simulated" if result.get("success") and result.get("mode") == "mock" else ("success" if result.get("success") else "failed"),
            request_payload_json=json.dumps(request_payload, ensure_ascii=False),
            response_payload_json=json.dumps(
                {
                    "status_code": result.get("status_code"),
                    "response": result.get("response"),
                    "error": result.get("error"),
                },
                ensure_ascii=False,
                default=str,
            ),
            error_message=result.get("error"),
            attempt_no=attempt_no,
        )
        self.db.add(log)
        self.db.flush()

    def _send_text(self, reminder: Reminder, mentioned_userids: list[str] | None) -> dict[str, object]:
        try:
            return self.wecom_adapter.send_text(
                reminder.group_id,
                reminder.content,
                mentioned_userids=mentioned_userids,
                tenant_id=reminder.tenant_id,
            )
        except TypeError as exc:
            if "tenant_id" not in str(exc):
                raise
            return self.wecom_adapter.send_text(reminder.group_id, reminder.content, mentioned_userids=mentioned_userids)

    def _infer_tenant_id_from_group(self, group_id: str) -> str | None:
        legal_case = self.db.scalar(
            select(LegalCase)
            .where(LegalCase.group_id == group_id)
            .where(LegalCase.tenant_id.is_not(None))
            .order_by(LegalCase.id.asc())
        )
        return legal_case.tenant_id if legal_case else None

    def _max_retry_for_tenant(self, tenant_id: str | None) -> int:
        if tenant_id is None:
            return self.wecom_adapter.settings.wecom_max_retry
        effective = TenantSettingsService(self.db).get_effective_settings(tenant_id)
        return int(effective["wecom"].get("max_retry") or self.wecom_adapter.settings.wecom_max_retry)
