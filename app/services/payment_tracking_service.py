from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.utils.datetime_utils import now_tz


class PaymentTrackingService:
    """Build the payment-notice ledger from approved business records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_rows(
        self,
        *,
        case_ids: list[int] | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
        today: date | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        query = (
            select(LegalEvent, LegalCase)
            .join(LegalCase, LegalCase.id == LegalEvent.case_id)
            .where(LegalEvent.event_type == "payment_notice")
            .where(LegalEvent.attribution_status == "confirmed")
            .where(LegalEvent.business_status == "applied")
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
        return len(rows), rows[offset : offset + limit]

    def _build_rows(self, pairs: list[tuple[LegalEvent, LegalCase]], *, today: date) -> list[dict[str, Any]]:
        event_ids = [event.id for event, _case in pairs]
        case_ids = list({legal_case.id for _event, legal_case in pairs})
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.source_event_id.in_(event_ids))
                .where(Reminder.reminder_type == "payment_tracking")
                .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
            ).all()
        )
        payments = list(
            self.db.scalars(
                select(PaymentRecord)
                .where(PaymentRecord.case_id.in_(case_ids))
                .where(PaymentRecord.status == "approved")
                .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
            ).all()
        )
        reminders_by_event: dict[int, list[Reminder]] = defaultdict(list)
        for reminder in reminders:
            if reminder.source_event_id is not None:
                reminders_by_event[reminder.source_event_id].append(reminder)
        payments_by_case: dict[int, list[PaymentRecord]] = defaultdict(list)
        for payment in payments:
            payments_by_case[payment.case_id].append(payment)

        return [
            self._row(event, legal_case, reminders_by_event[event.id], payments_by_case[legal_case.id], today)
            for event, legal_case in pairs
        ]

    @staticmethod
    def _row(
        event: LegalEvent,
        legal_case: LegalCase,
        reminders: list[Reminder],
        payments: list[PaymentRecord],
        today: date,
    ) -> dict[str, Any]:
        effective_paid = sum((Decimal(str(item.amount)) for item in payments), Decimal("0"))
        required = Decimal(str(event.amount)) if event.amount is not None else None
        deadline = max((item.remind_at.date() for item in reminders), default=None)
        payment_status = PaymentTrackingService._payment_status(required, effective_paid, deadline, today)
        sent = [item for item in reminders if item.status == "sent"]
        failed = [item for item in reminders if item.status == "failed"]
        pending = [item for item in reminders if item.status == "pending"]
        if sent:
            latest = max((item.sent_at or item.remind_at for item in sent)).date().isoformat()
            tracking = f"{latest} 已催促 {len(sent)} 次"
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
        return {
            "event_id": event.id,
            "case_id": legal_case.id,
            "notice_date": (event.event_time.date() if event.event_time else event.created_at.date()),
            "plaintiff": legal_case.plaintiff_name,
            "defendant": legal_case.debtor_name,
            "case_no": legal_case.case_no,
            "payment_info": str(required.quantize(Decimal("0.01"))) if required is not None else event.extracted_text,
            "payment_status": payment_status,
            "tracking_status": tracking,
            "payment_deadline": deadline,
            "remaining_payment_time": remaining,
            "screenshot_media_file_id": screenshot.source_media_file_id if screenshot else None,
            "screenshot_url": (
                f"/api/v1/legal/media-files/{screenshot.source_media_file_id}/content" if screenshot else None
            ),
        }

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
