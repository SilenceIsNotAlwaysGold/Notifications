from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class WeComArchiveGroup(Base):
    __tablename__ = "wecom_archive_groups"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    room_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    wecomapi_room_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="discovered", index=True)
    group_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    access_policy: Mapped[str] = mapped_column(String(32), default="auto", index=True)
    features_json: Mapped[str] = mapped_column(Text, default="{}")
    internal_userids_json: Mapped[str] = mapped_column(Text, default="[]")
    alert_userids_json: Mapped[str] = mapped_column(Text, default="[]")
    question_timeout_minutes: Mapped[int] = mapped_column(Integer, default=5)
    seen_message_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
