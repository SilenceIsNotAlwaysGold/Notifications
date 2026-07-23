from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class LegalCase(Base):
    __tablename__ = "legal_cases"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    case_no: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    debtor_name: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    plaintiff_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    court_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    enforcement_case_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    responsible_contact_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    lifecycle_stage: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    extra_identifiers_json: Mapped[str] = mapped_column(Text, default="[]")
    debtor_wecom_userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lawyer_wecom_userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    overdue_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    defaulted_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    last_status_checked_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    repayment_reminder_created_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    default_upgrade_reminder_created_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)

    events = relationship("LegalEvent", back_populates="case")
    reminders = relationship("Reminder", back_populates="case")
    sync_logs = relationship("DocumentSyncLog", back_populates="case")
