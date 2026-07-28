import json
import re
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
from app.utils.regex_parser import is_payment_done_text

SYSTEM_MESSAGE_PREFIXES = (
    "【致和法务】",
    "【商家待回复】",
    "【缴费信息待核实】",
    "商家消息超过",
    "商家消息超时",
)

CONVERSATION_CLOSING_PATTERN = re.compile(
    r"^(?:"
    r"好(?:的|嘞|了)?|可以(?:的|了)?|行|没问题|嗯+|收到(?:了)?|已收到|知悉|明白|了解|"
    r"ok|okay|谢谢(?:你)?|感谢|辛苦了|多谢|"
    r"不用了|暂时不用了|不需要了|已解决|已经解决了?|"
    r"处理好了?|已处理好了?|已经处理好了?|没事了|"
    r"已缴费(?:了)?|已代缴(?:了)?|已收款(?:了)?|已付款(?:了)?|已支付(?:了)?|"
    r"支付成功|转账成功|付款完成|支付完成|缴费完成|"
    r"先这样|那就这样|这样就可以了|就这样就可以了|后续再联系|回头再联系"
    r")+$",
    re.IGNORECASE,
)

TEXT_PLACEHOLDER_PATTERN = re.compile(
    r"^[\[【](?:表情|动画表情|图片|语音|视频|文件|位置|链接|聊天记录)[\]】]$",
    re.IGNORECASE,
)

PAYMENT_SIGNALS = (
    "缴费",
    "诉讼费",
    "公告费",
    "保全费",
    "执行费",
    "付款",
    "支付",
    "转账",
    "还款",
    "回款",
    "到账",
    "退款",
    "金额",
    "费用",
    "收款",
    "欠款",
    "二维码",
    "付款码",
    "缴费码",
    "￥",
    "¥",
)

DEADLINE_SIGNALS = ("截止", "到期", "逾期", "超期", "尽快", "马上", "几点", "日期")

REQUEST_SIGNALS = (
    "麻烦",
    "请",
    "帮忙",
    "帮我",
    "能否",
    "可否",
    "是否",
    "是不是",
    "为什么",
    "怎么",
    "如何",
    "需要",
    "回复",
    "答复",
    "核实",
    "确认",
    "处理",
    "安排",
    "提供",
    "发一下",
    "查一下",
    "看一下",
    "看下",
    "码出一下",
    "多少钱",
    "多少",
)

ISSUE_SIGNALS = (
    "有问题",
    "不对",
    "错误",
    "弄错",
    "遗漏",
    "漏了",
    "重复起诉",
    "重复提交",
    "未收到",
    "没收到",
    "无法",
    "不能",
)

INSTRUCTION_SIGNALS = ("不要", "不用", "不需要", "取消", "停止", "撤回", "作废", "修改", "更正", "补充")

NO_REPLY_PHRASES = ("请谅解", "敬请谅解", "请知悉", "仅供参考", "无需回复", "不用回复")

RESPONSE_ACK_PATTERN = re.compile(
    r"^(?:稍等(?:一下|下)?|等一下|我(?:先)?(?:看|查|核实|确认)(?:一下|下)?|正在(?:看|查|核实|确认|处理)|马上(?:看|查|核实|确认|处理))$"
)

QUOTE_DIVIDER_PATTERN = re.compile(r"(?:\r?\n)(?:\s*-\s*){6,}(?:\r?\n)")


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

        quoted_reply, quoted_closed = self._consume_quoted_reply(message)
        if quoted_reply:
            return {"created": 0, "closed": quoted_closed}

        if self._is_response_acknowledgement(message.content or ""):
            closed = self._close_latest_other_sender_question(message)
            if closed:
                return {"created": 0, "closed": closed}

        internal_userids = set(self.group_service.internal_userids(group))
        if message.sender_id in internal_userids:
            closed = self._close_relevant_question(message)
            return {"created": 0, "closed": closed}
        if is_payment_done_text(message.content or "") or self._is_conversation_closing(message.content or ""):
            closed = self._close_sender_question(message)
            return {"created": 0, "closed": closed}
        if not self._requires_business_reply(message.content or ""):
            return {"created": 0, "closed": 0}

        existing = self.db.scalar(
            select(MerchantQuestion).where(MerchantQuestion.group_message_id == message.id)
        )
        if existing:
            return {"created": 0, "closed": 0}
        asked_at = ensure_aware(message.received_at)
        question = MerchantQuestion(
            tenant_id=message.tenant_id or group.tenant_id,
            group_id=message.group_id,
            group_message_id=message.id,
            sender_id=message.sender_id,
            content=(message.content or "").strip(),
            asked_at=asked_at,
            deadline_at=self._business_deadline(asked_at, group.question_timeout_minutes),
            status="open",
            assigned_userid=message.sender_id,
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
            target_userid = question.sender_id
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
            assigned = question.sender_id
            if assigned and question.assigned_userid is None:
                question.assigned_userid = assigned
            first_minutes = group.question_timeout_minutes
            followup_minutes = max(first_minutes + 1, self.settings.merchant_question_escalation_minutes)
            stages = [
                (followup_minutes, "merchant_question_followup", assigned, f"followup-{followup_minutes}"),
                (max(followup_minutes + 1, 60), "merchant_question_escalation", assigned, "escalation-60"),
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

    def _consume_quoted_reply(self, reply: GroupMessage) -> tuple[bool, int]:
        quoted_content = self._quoted_content(reply.content or "")
        if quoted_content is None:
            return False, 0
        questions = list(
            self.db.scalars(
                select(MerchantQuestion)
                .where(MerchantQuestion.group_id == reply.group_id)
                .where(MerchantQuestion.asked_at <= ensure_aware(reply.received_at))
                .order_by(MerchantQuestion.asked_at.desc(), MerchantQuestion.id.desc())
            ).all()
        )
        normalized_quote = self._normalized_match_text(quoted_content)
        question = next(
            (
                item
                for item in questions
                if self._normalized_match_text(item.content) in normalized_quote
                or normalized_quote in self._normalized_match_text(item.content)
            ),
            None,
        )
        if question is None or question.status not in {"open", "timed_out", "escalated"}:
            return True, 0
        question.status = "replied"
        question.reply_message_id = reply.id
        question.replied_at = ensure_aware(reply.received_at)
        question.updated_at = now_tz()
        self._cancel_pending_question_reminders(question, "群成员已引用回复发起人的问题", reply.sender_id)
        self.db.flush()
        return True, 1

    def _close_latest_other_sender_question(self, reply: GroupMessage) -> int:
        question = self.db.scalar(
            select(MerchantQuestion)
            .where(MerchantQuestion.group_id == reply.group_id)
            .where(MerchantQuestion.sender_id != reply.sender_id)
            .where(MerchantQuestion.status.in_(["open", "timed_out", "escalated"]))
            .where(MerchantQuestion.asked_at <= ensure_aware(reply.received_at))
            .order_by(MerchantQuestion.asked_at.desc(), MerchantQuestion.id.desc())
        )
        if question is None:
            return 0
        question.status = "replied"
        question.reply_message_id = reply.id
        question.replied_at = ensure_aware(reply.received_at)
        question.updated_at = now_tz()
        self._cancel_pending_question_reminders(question, "群成员已响应发起人的问题", reply.sender_id)
        self.db.flush()
        return 1

    def _close_sender_question(self, message: GroupMessage) -> int:
        question = self.db.scalar(
            select(MerchantQuestion)
            .where(MerchantQuestion.group_id == message.group_id)
            .where(MerchantQuestion.sender_id == message.sender_id)
            .where(MerchantQuestion.status.in_(["open", "timed_out", "escalated"]))
            .where(MerchantQuestion.asked_at <= ensure_aware(message.received_at))
            .order_by(MerchantQuestion.asked_at.desc(), MerchantQuestion.id.desc())
        )
        if not question:
            return 0
        question.status = "closed"
        question.closed_by = message.sender_id
        question.closed_at = ensure_aware(message.received_at)
        question.close_reason = "商家确认对话结束，无需回复"
        question.updated_at = now_tz()
        self._cancel_pending_question_reminders(question, question.close_reason, message.sender_id)
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
        cleaned = re.sub(r"^(?:@\S+\s*)+", "", content.strip())
        return any(cleaned.startswith(prefix) for prefix in SYSTEM_MESSAGE_PREFIXES)

    @staticmethod
    def _is_response_acknowledgement(content: str) -> bool:
        body = MerchantQuestionService._message_body(content)
        normalized = re.sub(r"[\s,，。.!！?？~～、;；:：\"'“”‘’()（）]+", "", body)
        return bool(normalized and RESPONSE_ACK_PATTERN.fullmatch(normalized))

    @staticmethod
    def _is_conversation_closing(content: str) -> bool:
        body = MerchantQuestionService._message_body(content)
        normalized = re.sub(r"[\s,，。.!！?？~～、;；:：\"'“”‘’()（）]+", "", body)
        return bool(normalized and CONVERSATION_CLOSING_PATTERN.fullmatch(normalized))

    @staticmethod
    def _requires_business_reply(content: str) -> bool:
        body = MerchantQuestionService._message_body(content)
        if not body or TEXT_PLACEHOLDER_PATTERN.fullmatch(body):
            return False
        if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", body):
            return False
        actionable_body = body
        for phrase in NO_REPLY_PHRASES:
            actionable_body = actionable_body.replace(phrase, "")
        if "?" in actionable_body or "？" in actionable_body:
            return True
        return any(
            signal in actionable_body
            for signals in (
                PAYMENT_SIGNALS,
                DEADLINE_SIGNALS,
                REQUEST_SIGNALS,
                ISSUE_SIGNALS,
                INSTRUCTION_SIGNALS,
            )
            for signal in signals
        )

    @staticmethod
    def _message_body(content: str) -> str:
        parts = QUOTE_DIVIDER_PATTERN.split(content, maxsplit=1)
        body = parts[-1].strip()
        if len(parts) == 1:
            body = content.rsplit("------", 1)[-1].strip()
        return re.sub(r"^(?:@\S+\s*)+", "", body).strip()

    @staticmethod
    def _quoted_content(content: str) -> str | None:
        parts = QUOTE_DIVIDER_PATTERN.split(content, maxsplit=1)
        if len(parts) == 1 and "------" in content:
            parts = content.split("------", 1)
        if len(parts) != 2:
            return None
        quoted = re.sub(r"^(?:@\S+\s*)+", "", parts[0].strip())
        quoted = re.sub(r"^这是一条引用/回复消息[：:]?", "", quoted).strip()
        quoted = quoted.strip('「」\"“”')
        if "：" in quoted:
            quoted = quoted.split("：", 1)[1]
        elif ":" in quoted:
            quoted = quoted.split(":", 1)[1]
        return quoted.strip() or None

    @staticmethod
    def _normalized_match_text(content: str) -> str:
        return re.sub(r"[\s「」\"“”'‘’]+", "", content or "")

    @staticmethod
    def _stage_content(minutes: int, content: str, escalated: bool = False) -> str:
        action = "已升级，请立即处理" if escalated else "请尽快回复"
        prefix = (
            "【缴费信息待核实】"
            if MerchantQuestionService._contains_payment_signal(content)
            else "【商家待回复】"
        )
        return f"{prefix}消息已等待 {minutes} 分钟，{action}：{content[:200]}"

    @staticmethod
    def _contains_payment_signal(content: str) -> bool:
        return any(signal in content for signal in PAYMENT_SIGNALS)

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
