from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class GroupMessage(Base):
    __tablename__ = "group_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    sender_id: Mapped[str] = mapped_column(String(128), index=True)
    msg_type: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)

    events = relationship("LegalEvent", back_populates="group_message")
