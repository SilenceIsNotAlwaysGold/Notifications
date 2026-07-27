import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.models.reminder import Reminder
from app.services.reminder_service import ReminderService
from app.utils.datetime_utils import now_tz


class PaymentService:
    EFFECTIVE_STATUSES = ("approved",)
    FEE_RECORD_TYPES = ("fee_payment", "fee_reversal")

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        legal_case: LegalCase,
        *,
        amount: Decimal,
        record_type: str = "payment",
        payment_date: date | None = None,
        payer_name: str | None = None,
        source_event: LegalEvent | None = None,
        source_media: MediaFile | None = None,
        applies_to_event_id: int | None = None,
        status: str = "pending",
        operator: str = "system",
        note: str | None = None,
        fingerprint: str | None = None,
    ) -> tuple[PaymentRecord, bool]:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValueError("付款金额必须大于 0")
        if applies_to_event_id is None and record_type == "fee_payment":
            applies_to_event_id = self._auto_match_notice(legal_case.id, amount)
        if applies_to_event_id is not None:
            self._payment_notice(legal_case.id, applies_to_event_id)
        fingerprint = fingerprint or self._fingerprint(legal_case.id, amount, source_event, source_media)
        existing = self.db.scalar(select(PaymentRecord).where(PaymentRecord.credential_fingerprint == fingerprint))
        if existing:
            return existing, False
        now = now_tz()
        record = PaymentRecord(
            tenant_id=legal_case.tenant_id,
            case_id=legal_case.id,
            source_event_id=source_event.id if source_event else None,
            applies_to_event_id=applies_to_event_id,
            source_media_file_id=source_media.id if source_media else None,
            record_type=record_type,
            amount=amount,
            payment_date=payment_date,
            payer_name=(payer_name or "").strip() or None,
            credential_fingerprint=fingerprint,
            status=status,
            note=note,
            approved_by=operator if status == "approved" else None,
            approved_at=now if status == "approved" else None,
            created_by=operator,
        )
        self.db.add(record)
        self.db.flush()
        if status == "approved":
            self.recalculate_case(legal_case)
            self._cancel_notice_reminders_if_paid(applies_to_event_id)
        return record, True

    def approve(self, record: PaymentRecord, operator: str) -> PaymentRecord:
        if record.status == "reversed":
            raise ValueError("已冲正付款不能批准")
        record.status = "approved"
        record.approved_by = operator
        record.approved_at = now_tz()
        self.recalculate_case(self.db.get(LegalCase, record.case_id))
        self._cancel_notice_reminders_if_paid(record.applies_to_event_id)
        return record

    def reverse(self, record: PaymentRecord, operator: str, note: str) -> PaymentRecord:
        if record.status != "approved":
            raise ValueError("仅已批准付款可以冲正")
        existing = self.db.scalar(select(PaymentRecord).where(PaymentRecord.reversal_of_id == record.id))
        if existing:
            return existing
        reversal = PaymentRecord(
            tenant_id=record.tenant_id,
            case_id=record.case_id,
            source_event_id=record.source_event_id,
            source_media_file_id=record.source_media_file_id,
            applies_to_event_id=record.applies_to_event_id,
            record_type="fee_reversal" if record.record_type == "fee_payment" else "reversal",
            amount=-record.amount,
            payment_date=now_tz().date(),
            credential_fingerprint=f"reversal:{record.id}",
            status="approved",
            reversal_of_id=record.id,
            note=note,
            approved_by=operator,
            approved_at=now_tz(),
            created_by=operator,
        )
        self.db.add(reversal)
        self.db.flush()
        self.recalculate_case(self.db.get(LegalCase, record.case_id))
        self._reopen_notice_reminders_if_unpaid(record.applies_to_event_id)
        if record.applies_to_event_id is not None:
            self._sync_notice_payment(record.applies_to_event_id, reversal)
        return reversal

    def assign_to_notice(self, record: PaymentRecord, notice_event_id: int, operator: str) -> PaymentRecord:
        if record.status != "approved":
            raise ValueError("仅已批准付款凭证可以关联缴费通知")
        if record.applies_to_event_id not in (None, notice_event_id):
            raise ValueError("该付款凭证已关联其他缴费通知")
        self._payment_notice(record.case_id, notice_event_id)
        record.applies_to_event_id = notice_event_id
        if record.record_type not in self.FEE_RECORD_TYPES:
            record.record_type = "fee_payment"
            record.note = self._append_note(record.note, f"由 {operator} 确认为法院费用付款")
        self.db.flush()
        self.recalculate_case(self.db.get(LegalCase, record.case_id))
        self._cancel_notice_reminders_if_paid(notice_event_id)
        self._sync_notice_payment(notice_event_id, record)
        return record

    def recalculate_case(self, legal_case: LegalCase | None) -> Decimal:
        if not legal_case:
            raise ValueError("案件不存在")
        total = self.db.scalar(
            select(func.coalesce(func.sum(PaymentRecord.amount), 0)).where(
                PaymentRecord.case_id == legal_case.id,
                PaymentRecord.status.in_(self.EFFECTIVE_STATUSES),
                PaymentRecord.record_type.notin_(self.FEE_RECORD_TYPES),
            )
        )
        paid = max(Decimal("0.00"), Decimal(str(total or 0)).quantize(Decimal("0.01")))
        legal_case.paid_amount = paid
        if paid >= legal_case.total_amount:
            legal_case.status = "paid"
            legal_case.paid_at = legal_case.paid_at or now_tz()
            ReminderService(self.db).cancel_pending_payment_tracking(legal_case.id, "案件已足额付款")
        elif legal_case.status == "paid":
            legal_case.status = "normal"
            legal_case.paid_at = None
        self.db.flush()
        return paid

    def list_for_case(self, case_id: int, *, offset: int = 0, limit: int = 100) -> tuple[int, list[PaymentRecord]]:
        query = select(PaymentRecord).where(PaymentRecord.case_id == case_id)
        total = int(self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        items = list(self.db.scalars(query.order_by(PaymentRecord.id.desc()).offset(offset).limit(limit)).all())
        return total, items

    def _auto_match_notice(self, case_id: int, amount: Decimal) -> int | None:
        notices = list(
            self.db.scalars(
                select(LegalEvent)
                .where(LegalEvent.case_id == case_id)
                .where(LegalEvent.event_type == "payment_notice")
                .where(LegalEvent.attribution_status == "confirmed")
                .where(LegalEvent.business_status.in_(("applied", "legacy_applied")))
                .order_by(LegalEvent.event_time.asc(), LegalEvent.id.asc())
            ).all()
        )
        open_notices: list[tuple[LegalEvent, Decimal | None]] = []
        exact: list[LegalEvent] = []
        for notice in notices:
            paid = self._notice_paid_amount(notice.id)
            required = Decimal(str(notice.amount)) if notice.amount is not None else None
            remaining = max(Decimal("0.00"), required - paid) if required is not None else None
            if remaining is None or remaining > 0:
                open_notices.append((notice, remaining))
                if remaining == amount:
                    exact.append(notice)
        if len(exact) == 1:
            return exact[0].id
        return open_notices[0][0].id if len(open_notices) == 1 else None

    def _payment_notice(self, case_id: int, event_id: int) -> LegalEvent:
        event = self.db.get(LegalEvent, event_id)
        if not event or event.case_id != case_id or event.event_type != "payment_notice":
            raise ValueError("缴费通知不存在或不属于该案件")
        if event.attribution_status != "confirmed" or event.business_status not in ("applied", "legacy_applied"):
            raise ValueError("缴费通知尚未确认生效")
        return event

    def _notice_paid_amount(self, event_id: int) -> Decimal:
        value = self.db.scalar(
            select(func.coalesce(func.sum(PaymentRecord.amount), 0)).where(
                PaymentRecord.applies_to_event_id == event_id,
                PaymentRecord.status.in_(self.EFFECTIVE_STATUSES),
                PaymentRecord.record_type.in_(self.FEE_RECORD_TYPES),
            )
        )
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))

    def _cancel_notice_reminders_if_paid(self, event_id: int | None) -> None:
        if event_id is None:
            return
        notice = self.db.get(LegalEvent, event_id)
        if not notice or notice.amount is None or self._notice_paid_amount(event_id) < Decimal(str(notice.amount)):
            return
        reminders = self.db.scalars(
            select(Reminder).where(
                Reminder.source_event_id == event_id,
                Reminder.reminder_type.in_(("payment_tracking", "payment_confirmation")),
                Reminder.status == "pending",
            )
        ).all()
        now = now_tz()
        for reminder in reminders:
            reminder.status = "cancelled"
            reminder.cancelled_at = now
            reminder.cancel_reason = "该笔法院费用已足额支付"

    def single_open_notice(self, case_id: int) -> tuple[LegalEvent, Decimal] | None:
        notices = list(
            self.db.scalars(
                select(LegalEvent)
                .where(LegalEvent.case_id == case_id)
                .where(LegalEvent.event_type == "payment_notice")
                .where(LegalEvent.attribution_status == "confirmed")
                .where(LegalEvent.business_status.in_(("applied", "legacy_applied")))
                .order_by(LegalEvent.event_time.asc(), LegalEvent.id.asc())
            ).all()
        )
        open_notices: list[tuple[LegalEvent, Decimal]] = []
        for notice in notices:
            if notice.amount is None:
                continue
            outstanding = max(Decimal("0.00"), Decimal(str(notice.amount)) - self._notice_paid_amount(notice.id))
            if outstanding > 0:
                open_notices.append((notice, outstanding))
        return open_notices[0] if len(open_notices) == 1 else None

    def _reopen_notice_reminders_if_unpaid(self, event_id: int | None) -> None:
        if event_id is None:
            return
        notice = self.db.get(LegalEvent, event_id)
        if not notice or notice.amount is None or self._notice_paid_amount(event_id) >= Decimal(str(notice.amount)):
            return
        now = now_tz()
        reminders = self.db.scalars(
            select(Reminder).where(
                Reminder.source_event_id == event_id,
                Reminder.reminder_type.in_(("payment_tracking", "payment_confirmation")),
                Reminder.status == "cancelled",
                Reminder.cancel_reason == "该笔法院费用已足额支付",
                Reminder.remind_at > now,
            )
        ).all()
        for reminder in reminders:
            reminder.status = "pending"
            reminder.cancelled_at = None
            reminder.cancel_reason = None

    def _sync_notice_payment(self, notice_event_id: int, record: PaymentRecord) -> None:
        from app.services.document_sync_service import DocumentSyncService
        from app.services.payment_tracking_service import PaymentTrackingService

        notice = self.db.get(LegalEvent, notice_event_id)
        if not notice:
            return
        row = PaymentTrackingService(self.db).get_row(notice_event_id)
        if row is None:
            return
        DocumentSyncService(self.db).sync_payment_receipt_allocation(notice, record, row)

    @staticmethod
    def _append_note(existing: str | None, addition: str) -> str:
        return f"{existing}；{addition}" if existing else addition

    @staticmethod
    def _fingerprint(case_id: int, amount: Decimal, event: LegalEvent | None, media: MediaFile | None) -> str:
        source = media.md5sum if media and media.md5sum else f"event:{event.id}" if event else f"manual:{now_tz().isoformat()}"
        return hashlib.sha256(f"{case_id}|{amount}|{source}".encode()).hexdigest()
