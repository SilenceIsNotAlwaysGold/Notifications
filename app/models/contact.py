from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(32), default="other", index=True)
    archive_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    wecomapi_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)


class ContactGroup(Base):
    __tablename__ = "contact_groups"
    __table_args__ = (UniqueConstraint("contact_id", "group_id", name="uq_contact_groups_contact_group"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    membership_status: Mapped[str] = mapped_column(String(32), default="observed", index=True)
    source: Mapped[str] = mapped_column(String(32), default="callback")
    last_seen_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
