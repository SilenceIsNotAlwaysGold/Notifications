from datetime import datetime

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True, index=True)
    allowed_group_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_case_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_tenant_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
    revoked_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
