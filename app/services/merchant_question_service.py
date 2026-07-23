import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.group_message import GroupMessage
from app.models.merchant_question import MerchantQuestion
from app.models.reminder import Reminder
from app.services.reminder_service import ReminderService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import ensure_aware, now_tz


class MerchantQuestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.group_service = WeComArchiveGroupService(db)

    def handle_message(self, message: GroupMessage) -> dict[str, int]:
        if message.msg_type != "text" or not (message.content or "").strip():
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
            deadline_at=asked_at + timedelta(minutes=group.question_timeout_minutes),
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
            dedupe_key = f"merchant-question:{question.id}:timeout"
            reminder = self.db.scalar(select(Reminder).where(Reminder.dedupe_key == dedupe_key))
            if reminder is None:
                reminder = Reminder(
                    tenant_id=question.tenant_id,
                    case_id=None,
                    group_id=question.group_id,
                    reminder_type="merchant_question_timeout",
                    remind_at=now,
                    content=f"商家消息超过 5 分钟未回复：{question.content[:200]}",
                    target_userid=question.assigned_userid,
                    dedupe_key=dedupe_key,
                    status="pending",
                )
                self.db.add(reminder)
                self.db.flush()
                created += 1
            question.reminder_id = reminder.id
            question.status = "timed_out"
            question.updated_at = now_tz()
        self.db.flush()
        return {"checked": len(questions), "created_reminders": created}

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
        if question.reminder_id:
            reminder = self.db.get(Reminder, question.reminder_id)
            if reminder and reminder.status == "pending":
                ReminderService(self.db).cancel_reminder(reminder, "关联商家提问已关闭", operator)
        self.db.flush()
        return question

    def _close_relevant_question(self, reply: GroupMessage) -> int:
        questions = list(
            self.db.scalars(
                select(MerchantQuestion)
                .where(MerchantQuestion.group_id == reply.group_id)
                .where(MerchantQuestion.status.in_(["open", "timed_out"]))
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
        if question.reminder_id:
            reminder = self.db.get(Reminder, question.reminder_id)
            if reminder and reminder.status == "pending":
                ReminderService(self.db).cancel_reminder(reminder, "内部人员已回复商家提问", reply.sender_id)
        self.db.flush()
        return 1

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
