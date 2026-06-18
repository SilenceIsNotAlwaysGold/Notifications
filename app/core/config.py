from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="legal-wecom-automation", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")
    database_url: str = Field(default="sqlite:///./legal_wecom.db", alias="DATABASE_URL")
    db_auto_create: bool = Field(default=True, alias="DB_AUTO_CREATE")
    timezone: str = Field(default="Asia/Shanghai", alias="TIMEZONE")
    auth_enabled: bool = Field(default=False, alias="AUTH_ENABLED")
    admin_api_keys: str = Field(default="", alias="ADMIN_API_KEYS")
    public_endpoints: str = Field(default="/api/v1/health,/api/v1/health/detail", alias="PUBLIC_ENDPOINTS")
    rbac_enabled: bool = Field(default=True, alias="RBAC_ENABLED")
    default_api_key_role: str = Field(default="admin", alias="DEFAULT_API_KEY_ROLE")
    resource_scope_enabled: bool = Field(default=True, alias="RESOURCE_SCOPE_ENABLED")
    tenant_enabled: bool = Field(default=True, alias="TENANT_ENABLED")
    tenant_settings_enabled: bool = Field(default=True, alias="TENANT_SETTINGS_ENABLED")
    secret_value_mask: str = Field(default="******", alias="SECRET_VALUE_MASK")
    tenant_secret_encryption_key: str | None = Field(default=None, alias="TENANT_SECRET_ENCRYPTION_KEY")
    wecom_send_mode: Literal["mock", "webhook"] = Field(default="mock", alias="WECOM_SEND_MODE")
    wecom_webhook_url: str | None = Field(default=None, alias="WECOM_WEBHOOK_URL")
    wecom_timeout_seconds: int = Field(default=8, gt=0, alias="WECOM_TIMEOUT_SECONDS")
    wecom_max_retry: int = Field(default=3, ge=1, alias="WECOM_MAX_RETRY")
    wecom_archive_mode: Literal["mock", "real"] = Field(default="mock", alias="WECOM_ARCHIVE_MODE")
    wecom_corp_id: str | None = Field(default=None, alias="WECOM_CORP_ID")
    wecom_archive_secret: str | None = Field(default=None, alias="WECOM_ARCHIVE_SECRET")
    wecom_archive_private_key_path: str | None = Field(default=None, alias="WECOM_ARCHIVE_PRIVATE_KEY_PATH")
    wecom_archive_public_key_ver: str | None = Field(default=None, alias="WECOM_ARCHIVE_PUBLIC_KEY_VER")
    wecom_archive_seq_file: str = Field(default="./wecom_archive_seq.txt", alias="WECOM_ARCHIVE_SEQ_FILE")
    wecom_archive_limit: int = Field(default=100, ge=1, le=1000, alias="WECOM_ARCHIVE_LIMIT")
    wecom_archive_timeout_seconds: int = Field(default=10, gt=0, alias="WECOM_ARCHIVE_TIMEOUT_SECONDS")
    wecom_archive_auto_pull: bool = Field(default=False, alias="WECOM_ARCHIVE_AUTO_PULL")
    media_storage_dir: str = Field(default="./storage/media", alias="MEDIA_STORAGE_DIR")
    media_public_base_url: str | None = Field(default=None, alias="MEDIA_PUBLIC_BASE_URL")
    media_download_mode: Literal["mock", "real"] = Field(default="mock", alias="MEDIA_DOWNLOAD_MODE")
    media_max_file_size_mb: int = Field(default=50, ge=1, alias="MEDIA_MAX_FILE_SIZE_MB")
    tencent_doc_mode: Literal["mock", "real"] = Field(default="mock", alias="TENCENT_DOC_MODE")
    tencent_doc_base_url: str | None = Field(default=None, alias="TENCENT_DOC_BASE_URL")
    tencent_doc_app_id: str | None = Field(default=None, alias="TENCENT_DOC_APP_ID")
    tencent_doc_app_secret: str | None = Field(default=None, alias="TENCENT_DOC_APP_SECRET")
    tencent_doc_access_token: str | None = Field(default=None, alias="TENCENT_DOC_ACCESS_TOKEN")
    tencent_doc_sheet_id: str | None = Field(default=None, alias="TENCENT_DOC_SHEET_ID")
    tencent_doc_timeout_seconds: int = Field(default=10, gt=0, alias="TENCENT_DOC_TIMEOUT_SECONDS")
    tencent_doc_case_no_column: str = Field(default="案号", alias="TENCENT_DOC_CASE_NO_COLUMN")
    tencent_doc_status_column: str = Field(default="状态", alias="TENCENT_DOC_STATUS_COLUMN")
    tencent_doc_paid_amount_column: str = Field(default="已还金额", alias="TENCENT_DOC_PAID_AMOUNT_COLUMN")
    tencent_doc_archive_sheet_name: str = Field(default="资料台账", alias="TENCENT_DOC_ARCHIVE_SHEET_NAME")
    tencent_doc_case_sheet_name: str = Field(default="案件台账", alias="TENCENT_DOC_CASE_SHEET_NAME")
    repayment_reminder_days_before: int = Field(default=3, ge=0, alias="REPAYMENT_REMINDER_DAYS_BEFORE")
    default_upgrade_days_after_overdue: int = Field(default=3, ge=1, alias="DEFAULT_UPGRADE_DAYS_AFTER_OVERDUE")
    case_status_scan_enabled: bool = Field(default=True, alias="CASE_STATUS_SCAN_ENABLED")
    case_status_scan_hour: int = Field(default=1, ge=0, le=23, alias="CASE_STATUS_SCAN_HOUR")
    case_status_scan_minute: int = Field(default=0, ge=0, le=59, alias="CASE_STATUS_SCAN_MINUTE")
    ocr_provider: Literal["mock", "local_text", "tencent", "aliyun"] = Field(default="mock", alias="OCR_PROVIDER")
    ocr_enable_reprocess: bool = Field(default=True, alias="OCR_ENABLE_REPROCESS")
    ocr_max_text_length: int = Field(default=20000, ge=1, alias="OCR_MAX_TEXT_LENGTH")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def scheduler_enabled(self) -> bool:
        return self.app_env != "test"

    @property
    def admin_api_key_list(self) -> list[str]:
        return [key.strip() for key in (self.admin_api_keys or "").split(",") if key.strip()]

    @property
    def public_endpoint_list(self) -> list[str]:
        return [path.strip() for path in (self.public_endpoints or "").split(",") if path.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
