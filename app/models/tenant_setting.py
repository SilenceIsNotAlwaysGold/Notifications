from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class TenantSetting(Base):
    __tablename__ = "tenant_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    wecom_send_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wecom_webhook_url_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    wecom_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wecom_max_retry: Mapped[int | None] = mapped_column(Integer, nullable=True)

    tencent_doc_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tencent_doc_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tencent_doc_access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tencent_doc_sheet_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tencent_doc_case_sheet_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tencent_doc_archive_sheet_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tencent_doc_case_no_column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tencent_doc_status_column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tencent_doc_paid_amount_column: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tencent_doc_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    ocr_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_enable_reprocess: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocr_max_text_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    repayment_reminder_days_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_upgrade_days_after_overdue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    case_status_scan_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    keyword_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_flags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz)
    updated_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, onupdate=now_tz)
