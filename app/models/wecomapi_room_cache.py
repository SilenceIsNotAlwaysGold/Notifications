from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class WeComApiRoomCache(Base):
    __tablename__ = "wecomapi_room_cache"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    guid: Mapped[str] = mapped_column(String(128), index=True)
    room_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    room_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_userid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    member_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="callback", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    last_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
