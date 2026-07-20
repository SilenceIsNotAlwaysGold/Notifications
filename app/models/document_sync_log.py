from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class DocumentSyncLog(Base):
    __tablename__ = "document_sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    sync_type: Mapped[str] = mapped_column(String(64), index=True)
    sync_target: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_sheet_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_row_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    request_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    response_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)

    case = relationship("LegalCase", back_populates="sync_logs")
