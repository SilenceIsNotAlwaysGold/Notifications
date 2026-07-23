import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.legal_case import LegalCase
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.payment_record import PaymentRecord
from app.services.reminder_service import ReminderService
from app.utils.datetime_utils import now_tz


class PaymentService:
    EFFECTIVE_STATUSES = ("approved",)

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
        status: str = "pending",
        operator: str = "system",
        note: str | None = None,
        fingerprint: str | None = None,
    ) -> tuple[PaymentRecord, bool]:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValueError("付款金额必须大于 0")
        fingerprint = fingerprint or self._fingerprint(legal_case.id, amount, source_event, source_media)
        existing = self.db.scalar(select(PaymentRecord).where(PaymentRecord.credential_fingerprint == fingerprint))
        if existing:
            return existing, False
        now = now_tz()
        record = PaymentRecord(
            tenant_id=legal_case.tenant_id,
            case_id=legal_case.id,
            source_event_id=source_event.id if source_event else None,
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
        return record, True

    def approve(self, record: PaymentRecord, operator: str) -> PaymentRecord:
        if record.status == "reversed":
            raise ValueError("已冲正付款不能批准")
        record.status = "approved"
        record.approved_by = operator
        record.approved_at = now_tz()
        self.recalculate_case(self.db.get(LegalCase, record.case_id))
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
            record_type="reversal",
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
        return reversal

    def recalculate_case(self, legal_case: LegalCase | None) -> Decimal:
        if not legal_case:
            raise ValueError("案件不存在")
        total = self.db.scalar(
            select(func.coalesce(func.sum(PaymentRecord.amount), 0)).where(
                PaymentRecord.case_id == legal_case.id,
                PaymentRecord.status.in_(self.EFFECTIVE_STATUSES),
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

    @staticmethod
    def _fingerprint(case_id: int, amount: Decimal, event: LegalEvent | None, media: MediaFile | None) -> str:
        source = media.md5sum if media and media.md5sum else f"event:{event.id}" if event else f"manual:{now_tz().isoformat()}"
        return hashlib.sha256(f"{case_id}|{amount}|{source}".encode()).hexdigest()
