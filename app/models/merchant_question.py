from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class MerchantQuestion(Base):
    __tablename__ = "merchant_questions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    group_message_id: Mapped[int] = mapped_column(ForeignKey("group_messages.id"), unique=True, index=True)
    sender_id: Mapped[str] = mapped_column(String(128), index=True)
    content: Mapped[str] = mapped_column(Text)
    asked_at: Mapped[datetime] = mapped_column(AwareDateTime, index=True)
    deadline_at: Mapped[datetime] = mapped_column(AwareDateTime, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    reply_message_id: Mapped[int | None] = mapped_column(ForeignKey("group_messages.id"), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    reminder_id: Mapped[int | None] = mapped_column(ForeignKey("reminders.id"), nullable=True, index=True)
    assigned_userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
