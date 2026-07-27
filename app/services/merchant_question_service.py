import json
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.group_message import GroupMessage
from app.models.merchant_question import MerchantQuestion
from app.models.reminder import Reminder
from app.core.config import get_settings
from app.services.reminder_service import ReminderService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import ensure_aware, now_tz

SYSTEM_MESSAGE_PREFIXES = (
    "【致和法务】",
    "【商家待回复】",
    "商家消息超过",
    "商家消息超时",
)


class MerchantQuestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.group_service = WeComArchiveGroupService(db)
        self.settings = get_settings()

    def handle_message(self, message: GroupMessage) -> dict[str, int]:
        if message.msg_type != "text" or not (message.content or "").strip():
            return {"created": 0, "closed": 0}
        if self._is_system_generated(message.content or ""):
            return {"created": 0, "closed": 0}
        group = self.group_service.get_group(message.group_id)
        if not group or group.group_type != "merchant":
            return {"created": 0, "closed": 0}
        if not self.group_service.feature_enabled(message.group_id, "question_timeout"):
            return {"created": 0, "closed": 0}

        internal_userids = set(self.group_service.internal_userids(group))
        if message.sender_id in internal_userids:
            closed = self._close_relevant_question(message)
            return {"created": 0, "closed": closed}

        existing = self.db.scalar(
            select(MerchantQuestion).where(MerchantQuestion.group_message_id == message.id)
        )
        if existing:
            return {"created": 0, "closed": 0}
        asked_at = ensure_aware(message.received_at)
        alert_userids = self.group_service.alert_userids(group)
        question = MerchantQuestion(
            tenant_id=message.tenant_id or group.tenant_id,
            group_id=message.group_id,
            group_message_id=message.id,
            sender_id=message.sender_id,
            content=(message.content or "").strip(),
            asked_at=asked_at,
            deadline_at=self._business_deadline(asked_at, group.question_timeout_minutes),
            status="open",
            assigned_userid=alert_userids[0] if alert_userids else None,
        )
        self.db.add(question)
        self.db.flush()
        return {"created": 1, "closed": 0}

    def scan_timeouts(self, current_time: datetime | None = None) -> dict[str, int]:
        now = ensure_aware(current_time) if current_time else now_tz()
        questions = list(
            self.db.scalars(
                select(MerchantQuestion)
                .where(MerchantQuestion.status == "open")
                .where(MerchantQuestion.deadline_at <= now)
                .order_by(MerchantQuestion.deadline_at.asc(), MerchantQuestion.id.asc())
            ).all()
        )
        created = 0
        for question in questions:
            group = self.group_service.get_group(question.group_id)
            if not group or not self.group_service.feature_enabled(question.group_id, "question_timeout"):
                continue
            dedupe_key = f"merchant-question:{question.id}:timeout"
            reminder = self.db.scalar(select(Reminder).where(Reminder.dedupe_key == dedupe_key))
            alert_userids = self.group_service.alert_userids(group)
            target_userid = question.assigned_userid or (alert_userids[0] if alert_userids else None)
            if target_userid and question.assigned_userid is None:
                question.assigned_userid = target_userid
            if reminder is None and target_userid:
                reminder = Reminder(
                    tenant_id=question.tenant_id,
                    case_id=None,
                    group_id=question.group_id,
                    reminder_type="merchant_question_timeout",
                    remind_at=now,
                    content=self._stage_content(group.question_timeout_minutes, question.content),
                    target_userid=target_userid,
                    dedupe_key=dedupe_key,
                    status="pending",
                )
                self.db.add(reminder)
                self.db.flush()
                created += 1
            if reminder is not None:
                question.reminder_id = reminder.id
            question.status = "timed_out"
            question.updated_at = now_tz()
        self.db.flush()
        escalated = self._create_escalations(now)
        self.db.flush()
        return {"checked": len(questions), "created_reminders": created, "created_escalations": escalated}

    def _create_escalations(self, now: datetime) -> int:
        questions = list(
            self.db.scalars(
                select(MerchantQuestion)
                .where(MerchantQuestion.status == "timed_out")
                .order_by(MerchantQuestion.deadline_at.asc(), MerchantQuestion.id.asc())
            ).all()
        )
        created = 0
        for question in questions:
            group = self.group_service.get_group(question.group_id)
            if not group or not self.group_service.feature_enabled(question.group_id, "question_timeout"):
                continue
            alert_userids = self.group_service.alert_userids(group)
            assigned = question.assigned_userid or (alert_userids[0] if alert_userids else None)
            if assigned and question.assigned_userid is None:
                question.assigned_userid = assigned
            escalation_target = alert_userids[1] if len(alert_userids) > 1 else assigned
            first_minutes = group.question_timeout_minutes
            followup_minutes = max(first_minutes + 1, self.settings.merchant_question_escalation_minutes)
            stages = [
                (followup_minutes, "merchant_question_followup", assigned, f"followup-{followup_minutes}"),
                (max(followup_minutes + 1, 60), "merchant_question_escalation", escalation_target, "escalation-60"),
            ]
            for minutes, reminder_type, target_userid, stage_key in stages:
                if not target_userid or self._business_deadline(question.asked_at, minutes) > now:
                    continue
                dedupe_key = f"merchant-question:{question.id}:{stage_key}"
                if self.db.scalar(select(Reminder.id).where(Reminder.dedupe_key == dedupe_key)) is not None:
                    if reminder_type == "merchant_question_escalation":
                        question.status = "escalated"
                    continue
                self.db.add(
                    Reminder(
                        tenant_id=question.tenant_id,
                        case_id=None,
                        group_id=question.group_id,
                        reminder_type=reminder_type,
                        remind_at=now,
                        content=self._stage_content(
                            minutes,
                            question.content,
                            escalated=reminder_type == "merchant_question_escalation",
                        ),
                        target_userid=target_userid,
                        dedupe_key=dedupe_key,
                        status="pending",
                    )
                )
                created += 1
                if reminder_type == "merchant_question_escalation":
                    question.status = "escalated"
        return created

    def _business_deadline(self, asked_at: datetime, timeout_minutes: int) -> datetime:
        current = ensure_aware(asked_at)
        workdays = set(self.settings.merchant_workday_list)
        start = self._clock(self.settings.merchant_workday_start)
        end = self._clock(self.settings.merchant_workday_end)
        if start >= end:
            return current + timedelta(minutes=timeout_minutes)
        remaining = timedelta(minutes=timeout_minutes)
        while True:
            if current.weekday() not in workdays or current.timetz().replace(tzinfo=None) >= end:
                current = self._next_workday_start(current, workdays, start)
            elif current.timetz().replace(tzinfo=None) < start:
                current = datetime.combine(current.date(), start, tzinfo=current.tzinfo)
            work_end = datetime.combine(current.date(), end, tzinfo=current.tzinfo)
            available = work_end - current
            if remaining <= available:
                return current + remaining
            remaining -= available
            current = self._next_workday_start(current, workdays, start)

    @staticmethod
    def _clock(value: str) -> time:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))

    @staticmethod
    def _next_workday_start(current: datetime, workdays: set[int], start: time) -> datetime:
        day = current.date() + timedelta(days=1)
        while day.weekday() not in workdays:
            day += timedelta(days=1)
        return datetime.combine(day, start, tzinfo=current.tzinfo)

    def list_questions(
        self,
        status: str | None = None,
        group_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[int, list[MerchantQuestion]]:
        query = select(MerchantQuestion)
        if status:
            query = query.where(MerchantQuestion.status == status)
        if group_id:
            query = query.where(MerchantQuestion.group_id == group_id)
        total = int(self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        items = list(
            self.db.scalars(
                query.order_by(MerchantQuestion.asked_at.desc(), MerchantQuestion.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return total, items

    def close_question(self, question_id: int, operator: str, reason: str) -> MerchantQuestion:
        question = self.db.get(MerchantQuestion, question_id)
        if not question:
            raise ValueError("商家提问不存在")
        if question.status in {"replied", "closed"}:
            return question
        question.status = "closed"
        question.closed_by = operator
        question.closed_at = now_tz()
        question.close_reason = reason
        self._cancel_pending_question_reminders(question, "关联商家提问已关闭", operator)
        self.db.flush()
        return question

    def _close_relevant_question(self, reply: GroupMessage) -> int:
        questions = list(
            self.db.scalars(
                select(MerchantQuestion)
                .where(MerchantQuestion.group_id == reply.group_id)
                .where(MerchantQuestion.status.in_(["open", "timed_out", "escalated"]))
                .where(MerchantQuestion.asked_at <= ensure_aware(reply.received_at))
                .order_by(MerchantQuestion.asked_at.desc(), MerchantQuestion.id.desc())
            ).all()
        )
        if not questions:
            return 0
        referenced_ids = self._referenced_message_ids(reply.raw_payload_json)
        question = next((item for item in questions if item.group_message_id in referenced_ids), questions[0])
        question.status = "replied"
        question.reply_message_id = reply.id
        question.replied_at = ensure_aware(reply.received_at)
        question.updated_at = now_tz()
        self._cancel_pending_question_reminders(question, "内部人员已回复商家提问", reply.sender_id)
        self.db.flush()
        return 1

    def _cancel_pending_question_reminders(self, question: MerchantQuestion, reason: str, operator: str) -> None:
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.dedupe_key.like(f"merchant-question:{question.id}:%"))
                .where(Reminder.status == "pending")
            ).all()
        )
        for reminder in reminders:
            ReminderService(self.db).cancel_reminder(reminder, reason, operator)

    @staticmethod
    def _is_system_generated(content: str) -> bool:
        cleaned = content.strip()
        return any(cleaned.startswith(prefix) for prefix in SYSTEM_MESSAGE_PREFIXES)

    @staticmethod
    def _stage_content(minutes: int, content: str, escalated: bool = False) -> str:
        action = "已升级，请立即处理" if escalated else "请尽快回复"
        return f"【商家待回复】消息已等待 {minutes} 分钟，{action}：{content[:200]}"

    @staticmethod
    def _referenced_message_ids(raw_payload_json: str) -> set[int]:
        try:
            payload = json.loads(raw_payload_json or "{}")
        except (TypeError, ValueError):
            return set()
        found: set[int] = set()

        def walk(value, key: str = "") -> None:
            if isinstance(value, dict):
                for child_key, child in value.items():
                    walk(child, str(child_key).lower())
            elif isinstance(value, list):
                for child in value:
                    walk(child, key)
            elif key in {"reply_to_message_id", "referenced_message_id", "quoted_message_id", "source_message_id"}:
                try:
                    found.add(int(value))
                except (TypeError, ValueError):
                    pass

        walk(payload)
        return found
