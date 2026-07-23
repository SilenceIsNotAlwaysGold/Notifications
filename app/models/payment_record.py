from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("legal_cases.id"), index=True)
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("legal_events.id"), nullable=True, index=True)
    source_media_file_id: Mapped[int | None] = mapped_column(ForeignKey("legal_media_files.id"), nullable=True, index=True)
    record_type: Mapped[str] = mapped_column(String(32), default="payment", index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("payment_records.id"), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), default="system")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
