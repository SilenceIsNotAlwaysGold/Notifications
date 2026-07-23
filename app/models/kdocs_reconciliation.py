from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class KDocsReconciliation(Base):
    __tablename__ = "kdocs_reconciliations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    sync_log_id: Mapped[int | None] = mapped_column(ForeignKey("document_sync_logs.id"), nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(32), index=True)
    external_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    expected_json: Mapped[str] = mapped_column(Text, default="{}")
    actual_json: Mapped[str] = mapped_column(Text, default="{}")
    differences_json: Mapped[str] = mapped_column(Text, default="{}")
    checked_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
