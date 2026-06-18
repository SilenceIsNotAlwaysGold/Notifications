import logging
import json
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.wecom_message import WeComMessageAdapter
from app.models.legal_case import LegalCase
from app.models.reminder import Reminder
from app.models.reminder_send_log import ReminderSendLog
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
        remind_at = self._default_today_remind_at()
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

    def create_default_upgrade_reminder(self, case_id: int) -> Reminder:
        legal_case = self.db.get(LegalCase, case_id)
        if not legal_case:
            raise ValueError("案件不存在")
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

    def create_payment_tracking(self, case_id: int | None, start_date: date, days: int = 7) -> list[Reminder]:
        legal_case = self.db.get(LegalCase, case_id) if case_id else None
        if case_id and not legal_case:
            raise ValueError("案件不存在")
        if not legal_case:
            return []

        group_id = legal_case.group_id
        case_no = legal_case.case_no
        reminders = []
        for day in range(days):
            remind_at = start_of_day(start_date + timedelta(days=day))
            reminders.append(
                self._create(
                    case_id=case_id,
                    tenant_id=legal_case.tenant_id,
                    group_id=group_id,
                    reminder_type="payment_tracking",
                    remind_at=remind_at,
                    content=f"缴费通知跟踪提醒：案件{case_no}存在待缴费事项，请确认是否已完成缴费。",
                    target_userid=legal_case.lawyer_wecom_userid,
                    flush=False,
                )
            )
        self.db.flush()
        return reminders

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
            summary = {"sent": sent, "failed": failed, "retrying": retrying, "total": len(due_reminders), **({"operator": operator} if operator else {})}
            if failed:
                run_service.finish_partial(run_log, summary=summary, total_count=len(due_reminders), success_count=sent, failed_count=failed)
            else:
                run_service.finish_success(run_log, summary=summary, total_count=len(due_reminders), success_count=sent, failed_count=failed)
        except Exception as exc:
            run_service.finish_failed(
                run_log,
                str(exc),
                summary={"sent": sent, "failed": failed, "retrying": retrying, "total": len(due_reminders), **({"operator": operator} if operator else {})},
            )
            raise
        self.db.flush()
        return {"sent": sent, "failed": failed, "retrying": retrying, "total": len(due_reminders)}

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
            status="success" if result.get("success") else "failed",
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
