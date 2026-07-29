from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.contact import Contact, ContactGroup
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.models.wecom_archive_group import WeComArchiveGroup
from app.models.group_message import GroupMessage
from app.utils.regex_parser import parse_legal_text
from app.utils.datetime_utils import now_tz


class PaymentTrackingService:
    """Build the payment-notice ledger from approved business records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def reminder_destination(self, event: LegalEvent, legal_case: LegalCase) -> tuple[str, str | None]:
        """Resolve payment reminders to the source group and source sender."""
        return self.source_message_destination(
            event,
            fallback_group_id=legal_case.group_id,
            fallback_target_userid=legal_case.debtor_wecom_userid or legal_case.lawyer_wecom_userid,
        )

    def source_message_destination(
        self,
        event: LegalEvent,
        *,
        fallback_group_id: str,
        fallback_target_userid: str | None = None,
    ) -> tuple[str, str | None]:
        message = event.group_message
        if message is None and event.group_message_id is not None:
            message = self.db.get(GroupMessage, event.group_message_id)
        if message is None:
            return fallback_group_id, fallback_target_userid

        sender_id = (message.sender_id or "").strip()
        if not sender_id:
            return message.group_id, None
        contact = self.db.scalar(
            select(Contact)
            .join(ContactGroup, ContactGroup.contact_id == Contact.id)
            .where(
                ContactGroup.group_id == message.group_id,
                ContactGroup.membership_status != "left",
                Contact.is_active.is_(True),
                (Contact.archive_user_id == sender_id) | (Contact.wecomapi_user_id == sender_id),
            )
            .order_by(Contact.wecomapi_user_id.is_(None), Contact.last_confirmed_at.desc(), Contact.id.desc())
            .limit(1)
        )
        return message.group_id, (contact.wecomapi_user_id if contact and contact.wecomapi_user_id else sender_id)

    def confirm_standalone_notice(self, message: GroupMessage, extracted: dict[str, Any]) -> list[int]:
        candidates = list(
            self.db.scalars(
                select(LegalEvent)
                .join(GroupMessage, GroupMessage.id == LegalEvent.group_message_id)
                .where(
                    GroupMessage.group_id == message.group_id,
                    LegalEvent.event_type == "payment_notice",
                )
                .order_by(LegalEvent.id.desc())
                .limit(100)
            ).all()
        )
        events = {
            event.id: event
            for event in candidates
            if not self._metadata(event).get("standalone_payment_confirmation")
            and not self._metadata(event).get("superseded_by_payment_notice_event_id")
        }
        if not events:
            return []

        scored = [(self._confirmation_score(event, extracted, message.content or ""), event) for event in events.values()]
        best_score = max(score for score, _event in scored)
        matches = [event for score, event in scored if score == best_score and score > 0]
        if len(matches) != 1:
            matches = list(events.values()) if len(events) == 1 else []
        if len(matches) != 1:
            return []

        notice = matches[0]
        reminders = list(
            self.db.scalars(
                select(Reminder).where(
                    Reminder.source_event_id == notice.id,
                    Reminder.reminder_type.in_(("payment_confirmation", "payment_tracking")),
                    Reminder.status == "pending",
                )
            ).all()
        )
        now = now_tz()
        for reminder in reminders:
            reminder.status = "cancelled"
            reminder.cancelled_at = now
            reminder.cancel_reason = f"群消息 {message.id} 已明确确认缴费"
        metadata = self._metadata(notice)
        metadata["standalone_payment_confirmation"] = {
            "message_id": message.id,
            "confirmed_at": now.isoformat(),
        }
        notice.metadata_json = json.dumps(metadata, ensure_ascii=False)
        self.db.flush()
        return [reminder.id for reminder in reminders]

    def find_duplicate_open_notice(
        self,
        event: LegalEvent,
        message: GroupMessage,
        extracted: dict[str, Any],
    ) -> int | None:
        rows = self.db.execute(
            select(LegalEvent, GroupMessage)
            .join(GroupMessage, GroupMessage.id == LegalEvent.group_message_id)
            .join(Reminder, Reminder.source_event_id == LegalEvent.id)
            .where(
                LegalEvent.id != event.id,
                LegalEvent.event_type == "payment_notice",
                GroupMessage.group_id == message.group_id,
                Reminder.reminder_type == "payment_confirmation",
                Reminder.status == "pending",
            )
            .order_by(LegalEvent.id.desc())
        ).all()
        for candidate, candidate_message in rows:
            if self._same_notice(candidate, candidate_message, event, message, extracted):
                return candidate.id
        return None

    def supersede_open_notice_reminders(self, event_id: int, superseded_by_event_id: int) -> list[int]:
        reminders = list(
            self.db.scalars(
                select(Reminder).where(
                    Reminder.source_event_id == event_id,
                    Reminder.reminder_type == "payment_confirmation",
                    Reminder.status == "pending",
                )
            ).all()
        )
        now = now_tz()
        for reminder in reminders:
            reminder.status = "cancelled"
            reminder.cancelled_at = now
            reminder.cancel_reason = f"相同缴费通知已由事件 {superseded_by_event_id} 重新发送并重新计时"
        event = self.db.get(LegalEvent, event_id)
        if event is not None:
            metadata = self._metadata(event)
            metadata["superseded_by_payment_notice_event_id"] = superseded_by_event_id
            event.metadata_json = json.dumps(metadata, ensure_ascii=False)
        self.db.flush()
        return [reminder.id for reminder in reminders]

    @classmethod
    def _same_notice(
        cls,
        candidate: LegalEvent,
        candidate_message: GroupMessage,
        event: LegalEvent,
        message: GroupMessage,
        extracted: dict[str, Any],
    ) -> bool:
        candidate_metadata = cls._metadata(candidate)
        candidate_structured = candidate_metadata.get("structured_fields")
        if not isinstance(candidate_structured, dict):
            candidate_structured = {}
        incoming_metadata = extracted.get("metadata")
        if not isinstance(incoming_metadata, dict):
            incoming_metadata = {}
        incoming_structured = incoming_metadata.get("structured_fields")
        if not isinstance(incoming_structured, dict):
            incoming_structured = {}

        candidate_case = candidate_structured.get("case_no") or parse_legal_text(candidate.extracted_text).get("case_no")
        incoming_case = extracted.get("case_no") or incoming_structured.get("case_no")
        candidate_party = candidate_structured.get("defendant") or parse_legal_text(candidate.extracted_text).get("defendant")
        incoming_party = extracted.get("defendant") or incoming_structured.get("defendant")
        candidate_type = candidate_structured.get("payment_type")
        incoming_type = incoming_structured.get("payment_type")

        if candidate.amount != event.amount:
            return False
        if candidate_case and incoming_case:
            return cls._normalize_case_no(candidate_case) == cls._normalize_case_no(incoming_case)
        if candidate_party and incoming_party:
            return str(candidate_party).strip() == str(incoming_party).strip() and candidate_type == incoming_type
        return "".join((candidate_message.content or "").split()) == "".join((message.content or "").split())

    @staticmethod
    def _confirmation_score(event: LegalEvent, extracted: dict[str, Any], content: str) -> int:
        metadata = PaymentTrackingService._metadata(event)
        structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
        parsed = parse_legal_text(event.extracted_text)
        case_no = structured.get("case_no") or metadata.get("case_no") or parsed.get("case_no")
        defendant = structured.get("defendant") or metadata.get("defendant") or parsed.get("defendant")
        payment_type = structured.get("payment_type")
        incoming_case = extracted.get("case_no")
        incoming_defendant = extracted.get("defendant")
        incoming_type = (extracted.get("metadata") or {}).get("structured_fields", {}).get("payment_type")
        score = 0
        if incoming_case and case_no and PaymentTrackingService._normalize_case_no(incoming_case) == PaymentTrackingService._normalize_case_no(case_no):
            score += 100
        if defendant and (defendant == incoming_defendant or str(defendant) in content):
            score += 40
        if incoming_type and payment_type and incoming_type == payment_type:
            score += 10
        if extracted.get("amount") is not None and event.amount is not None and Decimal(str(extracted["amount"])) == Decimal(str(event.amount)):
            score += 20
        return score

    @staticmethod
    def _normalize_case_no(value: Any) -> str:
        return re.sub(r"[\s（）()]", "", str(value or "")).casefold()

    def repair_pending_reminder_destinations(self, *, dry_run: bool = True) -> dict[str, int]:
        rows = self.db.execute(
            select(Reminder, LegalEvent, LegalCase)
            .join(LegalEvent, LegalEvent.id == Reminder.source_event_id)
            .join(LegalCase, LegalCase.id == Reminder.case_id)
            .where(
                Reminder.status == "pending",
                Reminder.reminder_type.in_(("payment_tracking", "payment_confirmation")),
                LegalEvent.event_type == "payment_notice",
                LegalEvent.group_message_id.is_not(None),
            )
            .order_by(Reminder.id.asc())
        ).all()
        changed = 0
        for reminder, event, legal_case in rows:
            group_id, target_userid = self.reminder_destination(event, legal_case)
            if reminder.group_id == group_id and reminder.target_userid == target_userid:
                continue
            changed += 1
            if not dry_run:
                reminder.group_id = group_id
                reminder.target_userid = target_userid
        if not dry_run:
            self.db.flush()
        return {"checked": len(rows), "changed": changed}

    def list_rows(
        self,
        *,
        case_ids: list[int] | None = None,
        status: str | None = None,
        query_text: str = "",
        offset: int = 0,
        limit: int = 100,
        today: date | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        query = (
            select(LegalEvent, LegalCase)
            .join(LegalCase, LegalCase.id == LegalEvent.case_id)
            .where(LegalEvent.event_type == "payment_notice")
            .where(LegalEvent.attribution_status == "confirmed")
            .where(LegalEvent.business_status.in_(("applied", "legacy_applied")))
        )
        if case_ids is not None:
            if not case_ids:
                return 0, []
            query = query.where(LegalEvent.case_id.in_(case_ids))

        pairs = list(self.db.execute(query.order_by(LegalEvent.created_at.desc(), LegalEvent.id.desc())).all())
        if not pairs:
            return 0, []
        rows = self._build_rows(pairs, today=today or now_tz().date())
        if status:
            rows = [row for row in rows if row["payment_status"] == status]
        normalized_query = query_text.strip().casefold()
        if normalized_query:
            rows = [
                row
                for row in rows
                if any(
                    normalized_query in str(row.get(field) or "").casefold()
                    for field in ("plaintiff", "defendant", "case_no", "payment_type", "payment_info")
                )
            ]
        return len(rows), rows[offset : offset + limit]

    def _build_rows(self, pairs: list[tuple[LegalEvent, LegalCase]], *, today: date) -> list[dict[str, Any]]:
        event_ids = [event.id for event, _case in pairs]
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.source_event_id.in_(event_ids))
                .where(Reminder.reminder_type.in_(("payment_tracking", "payment_confirmation")))
                .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
            ).all()
        )
        payments = list(
            self.db.scalars(
                select(PaymentRecord)
                .where(PaymentRecord.applies_to_event_id.in_(event_ids))
                .where(PaymentRecord.status == "approved")
                .where(PaymentRecord.record_type.in_(("fee_payment", "fee_reversal")))
                .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
            ).all()
        )
        reminders_by_event: dict[int, list[Reminder]] = defaultdict(list)
        for reminder in reminders:
            if reminder.source_event_id is not None:
                reminders_by_event[reminder.source_event_id].append(reminder)
        payments_by_event: dict[int, list[PaymentRecord]] = defaultdict(list)
        for payment in payments:
            if payment.applies_to_event_id is not None:
                payments_by_event[payment.applies_to_event_id].append(payment)

        return [
            self._row(event, legal_case, reminders_by_event[event.id], payments_by_event[event.id], today)
            for event, legal_case in pairs
        ]

    def get_row(self, event_id: int, *, today: date | None = None) -> dict[str, Any] | None:
        pair = self.db.execute(
            select(LegalEvent, LegalCase)
            .join(LegalCase, LegalCase.id == LegalEvent.case_id)
            .where(LegalEvent.id == event_id)
            .where(LegalEvent.event_type == "payment_notice")
            .where(LegalEvent.attribution_status == "confirmed")
            .where(LegalEvent.business_status.in_(("applied", "legacy_applied")))
        ).one_or_none()
        if pair is None:
            return None
        rows = self._build_rows([pair], today=today or now_tz().date())
        return rows[0] if rows else None

    @staticmethod
    def _row(
        event: LegalEvent,
        legal_case: LegalCase,
        reminders: list[Reminder],
        payments: list[PaymentRecord],
        today: date,
    ) -> dict[str, Any]:
        effective_paid = sum((Decimal(str(item.amount)) for item in payments), Decimal("0"))
        effective_paid = max(Decimal("0.00"), effective_paid.quantize(Decimal("0.01")))
        required = Decimal(str(event.amount)) if event.amount is not None else None
        metadata = PaymentTrackingService._metadata(event)
        structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
        notice_date = event.event_time.date() if event.event_time else event.created_at.date()
        deadline = PaymentTrackingService._deadline(structured, notice_date, reminders)
        payment_type = PaymentTrackingService._payment_type(structured, event.extracted_text)
        payment_status = PaymentTrackingService._payment_status(required, effective_paid, deadline, today)
        sent = [item for item in reminders if item.status == "sent"]
        failed = [item for item in reminders if item.status == "failed"]
        pending = [item for item in reminders if item.status == "pending"]
        if sent:
            latest = max((item.sent_at or item.remind_at for item in sent)).date()
            tracking = f"{latest.year}年{latest.month}月{latest.day}日已催促{len(sent)}次"
        elif failed:
            tracking = f"催促失败 {len(failed)} 次"
        elif pending:
            tracking = f"待执行 {len(pending)} 次提醒"
        else:
            tracking = "未生成提醒"
        if payment_status == "paid":
            remaining = "已缴费"
        elif deadline is None:
            remaining = "待确认截止日"
        else:
            days = (deadline - today).days
            remaining = f"剩余 {days} 天" if days >= 0 else f"逾期 {abs(days)} 天"
        screenshot = next((item for item in payments if item.source_media_file_id), None)
        notice_media_id = metadata.get("media_file_id")
        receipt_urls = [
            f"/api/v1/legal/media-files/{item.source_media_file_id}/content"
            for item in payments
            if item.source_media_file_id is not None and item.amount > 0
        ]
        outstanding = max(Decimal("0.00"), required - effective_paid) if required is not None else None
        return {
            "event_id": event.id,
            "case_id": legal_case.id,
            "notice_date": notice_date,
            "plaintiff": legal_case.plaintiff_name,
            "defendant": legal_case.debtor_name,
            "case_no": legal_case.case_no,
            "payment_info": str(required.quantize(Decimal("0.01"))) if required is not None else event.extracted_text,
            "payment_type": payment_type,
            "required_amount": required,
            "paid_amount": effective_paid,
            "outstanding_amount": outstanding,
            "payment_status": payment_status,
            "tracking_status": tracking,
            "payment_deadline": deadline,
            "remaining_payment_time": remaining,
            "screenshot_media_file_id": screenshot.source_media_file_id if screenshot else None,
            "screenshot_url": (
                f"/api/v1/legal/media-files/{screenshot.source_media_file_id}/content" if screenshot else None
            ),
            "notice_screenshot_url": (
                f"/api/v1/legal/media-files/{notice_media_id}/content" if notice_media_id else None
            ),
            "receipt_urls": receipt_urls,
        }

    def list_unassigned_receipts(
        self,
        *,
        case_ids: list[int] | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[int, list[dict[str, Any]]]:
        query = (
            select(PaymentRecord, LegalCase)
            .join(LegalCase, LegalCase.id == PaymentRecord.case_id)
            .where(PaymentRecord.status == "approved")
            .where(PaymentRecord.record_type == "fee_payment")
            .where(PaymentRecord.applies_to_event_id.is_(None))
        )
        if case_ids is not None:
            if not case_ids:
                return 0, []
            query = query.where(PaymentRecord.case_id.in_(case_ids))
        pairs = list(self.db.execute(query.order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())).all())
        rows = [
            {
                "id": payment.id,
                "case_id": legal_case.id,
                "source_event_id": payment.source_event_id,
                "source_media_file_id": payment.source_media_file_id,
                "amount": payment.amount,
                "payment_date": payment.payment_date,
                "payer_name": payment.payer_name,
                "case_no": legal_case.case_no,
                "plaintiff": legal_case.plaintiff_name,
                "defendant": legal_case.debtor_name,
                "screenshot_url": (
                    f"/api/v1/legal/media-files/{payment.source_media_file_id}/content"
                    if payment.source_media_file_id
                    else None
                ),
            }
            for payment, legal_case in pairs
        ]
        return len(rows), rows[offset : offset + limit]

    def daily_summary(
        self,
        *,
        summary_date: date,
        case_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        query = (
            select(LegalEvent, LegalCase)
            .join(LegalCase, LegalCase.id == LegalEvent.case_id)
            .where(LegalEvent.event_type == "payment_notice")
            .where(LegalEvent.attribution_status == "confirmed")
            .where(LegalEvent.business_status.in_(("applied", "legacy_applied")))
        )
        if case_ids is not None:
            if not case_ids:
                return self._daily_summary_result(summary_date, [], [])
            query = query.where(LegalEvent.case_id.in_(case_ids))
        pairs = list(self.db.execute(query.order_by(LegalEvent.id.asc())).all())
        if not pairs:
            return self._daily_summary_result(summary_date, [], [])
        rows = self._build_rows(pairs, today=summary_date)
        events = {event.id: event for event, _case in pairs}
        event_ids = list(events)
        payment_records = list(
            self.db.scalars(
                select(PaymentRecord)
                .where(PaymentRecord.applies_to_event_id.in_(event_ids))
                .where(PaymentRecord.status == "approved")
                .where(PaymentRecord.record_type == "fee_payment")
            ).all()
        )
        confirmed_dates: dict[int, set[date]] = defaultdict(set)
        for payment in payment_records:
            confirmed_on = payment.payment_date or (payment.approved_at.date() if payment.approved_at else None)
            if payment.applies_to_event_id is not None and confirmed_on is not None:
                confirmed_dates[payment.applies_to_event_id].add(confirmed_on)
        group_ids = {
            event.group_message.group_id
            for event, _case in pairs
            if event.group_message is not None
        }
        group_names = {
            group.room_id: group.display_name or group.room_id
            for group in self.db.scalars(
                select(WeComArchiveGroup).where(WeComArchiveGroup.room_id.in_(group_ids))
            ).all()
        } if group_ids else {}
        sender_ids = {
            event.group_message.sender_id
            for event, _case in pairs
            if event.group_message is not None and event.group_message.sender_id
        }
        sender_names: dict[str, str] = {}
        if sender_ids:
            contacts = self.db.scalars(
                select(Contact).where(
                    (Contact.archive_user_id.in_(sender_ids)) | (Contact.wecomapi_user_id.in_(sender_ids))
                )
            ).all()
            for contact in contacts:
                if contact.archive_user_id:
                    sender_names[contact.archive_user_id] = contact.display_name
                if contact.wecomapi_user_id:
                    sender_names[contact.wecomapi_user_id] = contact.display_name
        confirmed: list[str] = []
        pending: list[str] = []
        for row in rows:
            event = events[row["event_id"]]
            message = event.group_message
            group_id = message.group_id if message else "未知群"
            group_name = group_names.get(group_id, group_id)
            sender_id = message.sender_id if message else None
            sender = sender_names.get(sender_id, sender_id or "来源待确认")
            party = "-".join(value for value in (row.get("plaintiff"), row.get("defendant")) if value)
            fee = f"{row.get('payment_type') or '缴费'}{self._money_text(row.get('required_amount'))}"
            prefix = f"{sender} - {group_name} - {party}{fee}"
            if row["payment_status"] == "paid":
                if summary_date not in confirmed_dates.get(row["event_id"], set()) and row["notice_date"] != summary_date:
                    continue
                confirmed.append(f"{prefix} - 已缴费")
            else:
                state = row.get("tracking_status") or row.get("remaining_payment_time") or "待跟进"
                pending.append(f"{prefix} - {state}")
        return self._daily_summary_result(summary_date, confirmed, pending)

    @staticmethod
    def _money_text(value: Any) -> str:
        if value is None:
            return ""
        return f"{Decimal(str(value)).quantize(Decimal('0.01'))}元"

    @staticmethod
    def _daily_summary_result(summary_date: date, confirmed: list[str], pending: list[str]) -> dict[str, Any]:
        weekdays = "一二三四五六日"
        lines = [
            f"【每日缴费信息汇总】{summary_date.year}年{summary_date.month}月{summary_date.day}日（周{weekdays[summary_date.weekday()]}）",
            "",
            "一、已确认收款/已缴费",
            "",
            *([f"{index}. {item}" for index, item in enumerate(confirmed, 1)] or ["暂无"]),
            "",
            "二、待确认/未支付的缴费",
            "",
            *([f"{index}. {item}" for index, item in enumerate(pending, 1)] or ["暂无"]),
        ]
        return {
            "summary_date": summary_date,
            "confirmed_count": len(confirmed),
            "pending_count": len(pending),
            "content": "\n".join(lines),
        }

    @staticmethod
    def _metadata(event: LegalEvent) -> dict[str, Any]:
        try:
            value = json.loads(event.metadata_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _deadline(structured: dict[str, Any], notice_date: date, reminders: list[Reminder]) -> date | None:
        raw_deadline = structured.get("payment_deadline")
        if raw_deadline:
            try:
                return date.fromisoformat(str(raw_deadline)[:10])
            except ValueError:
                pass
        try:
            term_days = int(structured.get("payment_term_days"))
        except (TypeError, ValueError):
            term_days = 0
        if term_days > 0:
            return notice_date + timedelta(days=term_days)
        return max((item.remind_at.date() for item in reminders), default=notice_date + timedelta(days=7))

    @staticmethod
    def _payment_type(structured: dict[str, Any], text: str | None) -> str:
        if structured.get("payment_type"):
            return str(structured["payment_type"])
        match = re.search(r"(案件受理费|诉讼费|公告费|执行费|保全费|开庭费|鉴定费)", text or "")
        return match.group(1) if match else "其他缴费"

    @staticmethod
    def _payment_status(
        required: Decimal | None,
        effective_paid: Decimal,
        deadline: date | None,
        today: date,
    ) -> str:
        if required is not None and effective_paid >= required:
            return "paid"
        if effective_paid > 0:
            return "partial"
        if deadline is not None and deadline < today:
            return "overdue"
        return "pending"
