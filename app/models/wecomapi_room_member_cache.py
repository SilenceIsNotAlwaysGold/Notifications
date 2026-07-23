from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class WeComApiRoomMemberCache(Base):
    __tablename__ = "wecomapi_room_member_cache"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_wecomapi_room_member"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    guid: Mapped[str] = mapped_column(String(128), index=True)
    room_id: Mapped[str] = mapped_column(String(128), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="callback", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    last_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
