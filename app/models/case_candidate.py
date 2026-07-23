from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class CaseCandidate(Base):
    __tablename__ = "case_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    normalized_case_no: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    case_no: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    debtor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey("group_messages.id"), nullable=True, index=True)
    source_media_file_id: Mapped[int | None] = mapped_column(ForeignKey("legal_media_files.id"), nullable=True, index=True)
    extracted_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    dismissed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    last_detected_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
