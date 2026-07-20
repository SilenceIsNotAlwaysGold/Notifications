from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    reminder_type: Mapped[str] = mapped_column(String(64), index=True)
    remind_at: Mapped[datetime] = mapped_column(AwareDateTime, index=True)
    content: Mapped[str] = mapped_column(Text)
    target_userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)

    case = relationship("LegalCase", back_populates="reminders")
