from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class LegalEvent(Base):
    __tablename__ = "legal_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    group_message_id: Mapped[int | None] = mapped_column(ForeignKey("group_messages.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_time: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)

    case = relationship("LegalCase", back_populates="events")
    group_message = relationship("GroupMessage", back_populates="events")
