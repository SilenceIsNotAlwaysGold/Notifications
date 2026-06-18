from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class CaseStatusHistory(Base):
    __tablename__ = "case_status_histories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("legal_cases.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    changed_by: Mapped[str] = mapped_column(String(64), default="system")
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
