from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class MediaFile(Base):
    __tablename__ = "legal_media_files"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    group_message_id: Mapped[int | None] = mapped_column(ForeignKey("group_messages.id"), nullable=True, index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("legal_cases.id"), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    msg_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    media_type: Mapped[str] = mapped_column(String(32), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    md5sum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="wecom_archive", index=True)
    source_payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    public_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    ocr_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), default="not_required", index=True)
    review_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_applied_at: Mapped[datetime | None] = mapped_column(AwareDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
