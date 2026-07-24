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
    wecom_send_mode: Literal["mock", "wecomapi"] = Field(default="wecomapi", alias="WECOM_SEND_MODE")
    wecom_timeout_seconds: int = Field(default=8, gt=0, alias="WECOM_TIMEOUT_SECONDS")
    wecom_max_retry: int = Field(default=3, ge=1, alias="WECOM_MAX_RETRY")
    wecomapi_base_url: str | None = Field(default=None, alias="WECOMAPI_BASE_URL")
    wecomapi_api_path: str = Field(default="/wecom/finder/api", alias="WECOMAPI_API_PATH")
    wecomapi_token: str | None = Field(default=None, alias="WECOMAPI_TOKEN")
    wecomapi_token_header: str = Field(
        default="WECOM-TOKEN",
        pattern=r"^[A-Za-z0-9-]+$",
        alias="WECOMAPI_TOKEN_HEADER",
    )
    wecomapi_guid: str | None = Field(default=None, alias="WECOMAPI_GUID")
    wecomapi_callback_path_secret: str | None = Field(default=None, alias="WECOMAPI_CALLBACK_PATH_SECRET")
    wecomapi_callback_max_bytes: int = Field(default=1048576, ge=1024, le=10485760, alias="WECOMAPI_CALLBACK_MAX_BYTES")
    wecomapi_callback_rate_per_minute: int = Field(default=120, ge=1, alias="WECOMAPI_CALLBACK_RATE_PER_MINUTE")
    wecomapi_min_interval_seconds: float = Field(default=3.0, ge=0, alias="WECOMAPI_MIN_INTERVAL_SECONDS")
    wecomapi_daily_limit: int = Field(default=200, ge=1, alias="WECOMAPI_DAILY_LIMIT")
    wecomapi_failure_threshold: int = Field(default=3, ge=1, alias="WECOMAPI_FAILURE_THRESHOLD")
    wecomapi_cooldown_seconds: int = Field(default=300, ge=1, alias="WECOMAPI_COOLDOWN_SECONDS")
    wecom_archive_mode: Literal["mock", "real"] = Field(default="mock", alias="WECOM_ARCHIVE_MODE")
    wecom_corp_id: str | None = Field(default=None, alias="WECOM_CORP_ID")
    wecom_archive_secret: str | None = Field(default=None, alias="WECOM_ARCHIVE_SECRET")
    wecom_archive_private_key_path: str | None = Field(default=None, alias="WECOM_ARCHIVE_PRIVATE_KEY_PATH")
    wecom_archive_public_key_ver: str | None = Field(default=None, alias="WECOM_ARCHIVE_PUBLIC_KEY_VER")
    wecom_archive_sidecar_url: str | None = Field(default=None, alias="WECOM_ARCHIVE_SIDECAR_URL")
    wecom_archive_sidecar_mock: bool = Field(default=False, alias="WECOM_ARCHIVE_SIDECAR_MOCK")
    wecom_archive_seq_file: str = Field(default="./wecom_archive_seq.txt", alias="WECOM_ARCHIVE_SEQ_FILE")
    wecom_archive_limit: int = Field(default=100, ge=1, le=1000, alias="WECOM_ARCHIVE_LIMIT")
    wecom_archive_timeout_seconds: int = Field(default=10, gt=0, alias="WECOM_ARCHIVE_TIMEOUT_SECONDS")
    wecom_archive_auto_pull: bool = Field(default=False, alias="WECOM_ARCHIVE_AUTO_PULL")
    media_storage_dir: str = Field(default="./storage/media", alias="MEDIA_STORAGE_DIR")
    media_public_base_url: str | None = Field(default=None, alias="MEDIA_PUBLIC_BASE_URL")
    media_download_mode: Literal["mock", "real"] = Field(default="mock", alias="MEDIA_DOWNLOAD_MODE")
    media_max_file_size_mb: int = Field(default=50, ge=1, alias="MEDIA_MAX_FILE_SIZE_MB")
    legal_data_retention_enabled: bool = Field(default=False, alias="LEGAL_DATA_RETENTION_ENABLED")
    legal_data_retention_days: int = Field(default=3650, ge=30, alias="LEGAL_DATA_RETENTION_DAYS")
    legal_data_retention_review_statuses: str = Field(default="rejected", alias="LEGAL_DATA_RETENTION_REVIEW_STATUSES")
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
    kdocs_mode: Literal["mock", "real"] = Field(default="mock", alias="KDOCS_MODE")
    kdocs_transport: Literal["gateway", "mcp"] = Field(default="gateway", alias="KDOCS_TRANSPORT")
    kdocs_base_url: str | None = Field(default=None, alias="KDOCS_BASE_URL")
    kdocs_access_token: str | None = Field(default=None, alias="KDOCS_ACCESS_TOKEN")
    kdocs_space_id: str | None = Field(default=None, alias="KDOCS_SPACE_ID")
    kdocs_timeout_seconds: int = Field(default=30, gt=0, alias="KDOCS_TIMEOUT_SECONDS")
    kdocs_mcp_url: str = Field(default="https://mcp-center.wps.cn/skill_hub/mcp", alias="KDOCS_MCP_URL")
    kdocs_mcp_skill_version: str = Field(default="1.3.6", alias="KDOCS_MCP_SKILL_VERSION")
    kdocs_mcp_client_id: str | None = Field(default=None, alias="KDOCS_MCP_CLIENT_ID")
    kdocs_drive_id: str | None = Field(default=None, alias="KDOCS_DRIVE_ID")
    kdocs_judgment_parent_id: str = Field(default="0", alias="KDOCS_JUDGMENT_PARENT_ID")
    kdocs_judgment_parent_path: str = Field(default="致和法务/判决书文件", alias="KDOCS_JUDGMENT_PARENT_PATH")
    kdocs_enforcement_file_id: str | None = Field(default=None, alias="KDOCS_ENFORCEMENT_FILE_ID")
    kdocs_enforcement_worksheet_id: int = Field(default=10, ge=0, alias="KDOCS_ENFORCEMENT_WORKSHEET_ID")
    kdocs_court_time_file_id: str | None = Field(default=None, alias="KDOCS_COURT_TIME_FILE_ID")
    kdocs_court_time_worksheet_id: int = Field(default=1, ge=0, alias="KDOCS_COURT_TIME_WORKSHEET_ID")
    kdocs_payment_file_id: str | None = Field(default=None, alias="KDOCS_PAYMENT_FILE_ID")
    kdocs_payment_worksheet_id: int = Field(default=1, ge=0, alias="KDOCS_PAYMENT_WORKSHEET_ID")
    kdocs_judgment_folder_id: str = Field(default="致和法务/判决书文件", alias="KDOCS_JUDGMENT_FOLDER_ID")
    kdocs_court_time_sheet_id: str = Field(default="致和法务/开庭时间", alias="KDOCS_COURT_TIME_SHEET_ID")
    kdocs_enforcement_sheet_id: str = Field(default="致和法务/强制执行进度表格", alias="KDOCS_ENFORCEMENT_SHEET_ID")
    kdocs_payment_sheet_id: str = Field(default="致和法务/缴费登记", alias="KDOCS_PAYMENT_SHEET_ID")
    kdocs_case_sheet_id: str = Field(default="致和法务/案件台账", alias="KDOCS_CASE_SHEET_ID")
    kdocs_case_no_column: str = Field(default="案号", alias="KDOCS_CASE_NO_COLUMN")
    kdocs_status_column: str = Field(default="状态", alias="KDOCS_STATUS_COLUMN")
    kdocs_paid_amount_column: str = Field(default="已还金额", alias="KDOCS_PAID_AMOUNT_COLUMN")
    repayment_reminder_days_before: int = Field(default=3, ge=0, alias="REPAYMENT_REMINDER_DAYS_BEFORE")
    default_upgrade_days_after_overdue: int = Field(default=3, ge=1, alias="DEFAULT_UPGRADE_DAYS_AFTER_OVERDUE")
    merchant_workday_start: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", alias="MERCHANT_WORKDAY_START")
    merchant_workday_end: str = Field(default="18:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$", alias="MERCHANT_WORKDAY_END")
    merchant_workdays: str = Field(default="0,1,2,3,4", alias="MERCHANT_WORKDAYS")
    merchant_question_escalation_minutes: int = Field(default=30, ge=1, le=10080, alias="MERCHANT_QUESTION_ESCALATION_MINUTES")
    case_status_scan_enabled: bool = Field(default=True, alias="CASE_STATUS_SCAN_ENABLED")
    case_status_scan_hour: int = Field(default=1, ge=0, le=23, alias="CASE_STATUS_SCAN_HOUR")
    case_status_scan_minute: int = Field(default=0, ge=0, le=59, alias="CASE_STATUS_SCAN_MINUTE")
    ocr_provider: Literal["mock", "local_text", "tencent", "aliyun"] = Field(default="mock", alias="OCR_PROVIDER")
    ocr_sidecar_url: str | None = Field(default=None, alias="OCR_SIDECAR_URL")
    ocr_enable_reprocess: bool = Field(default=True, alias="OCR_ENABLE_REPROCESS")
    ocr_max_text_length: int = Field(default=20000, ge=1, alias="OCR_MAX_TEXT_LENGTH")
    tencent_ocr_secret_id: str | None = Field(default=None, alias="TENCENT_OCR_SECRET_ID")
    tencent_ocr_secret_key: str | None = Field(default=None, alias="TENCENT_OCR_SECRET_KEY")
    tencent_ocr_region: str = Field(default="ap-guangzhou", alias="TENCENT_OCR_REGION")
    tencent_ocr_pdf_max_pages: int = Field(default=20, ge=1, le=20, alias="TENCENT_OCR_PDF_MAX_PAGES")
    tencent_ocr_timeout_seconds: int = Field(default=20, gt=0, alias="TENCENT_OCR_TIMEOUT_SECONDS")
    legal_extraction_mode: Literal["regex", "llm"] = Field(default="regex", alias="LEGAL_EXTRACTION_MODE")
    legal_llm_base_url: str | None = Field(default=None, alias="LEGAL_LLM_BASE_URL")
    legal_llm_api_key: str | None = Field(default=None, alias="LEGAL_LLM_API_KEY")
    legal_llm_model: str | None = Field(default=None, alias="LEGAL_LLM_MODEL")
    legal_llm_timeout_seconds: int = Field(default=30, gt=0, alias="LEGAL_LLM_TIMEOUT_SECONDS")
    legal_llm_max_text_length: int = Field(default=16000, ge=1000, alias="LEGAL_LLM_MAX_TEXT_LENGTH")
    legal_llm_min_confidence: float = Field(default=0.75, ge=0, le=1, alias="LEGAL_LLM_MIN_CONFIDENCE")
    legal_llm_fallback_to_regex: bool = Field(default=True, alias="LEGAL_LLM_FALLBACK_TO_REGEX")
    ops_alerts_enabled: bool = Field(default=True, alias="OPS_ALERTS_ENABLED")
    ops_scan_interval_minutes: int = Field(default=5, ge=1, alias="OPS_SCAN_INTERVAL_MINUTES")
    ops_failure_threshold: int = Field(default=3, ge=1, alias="OPS_FAILURE_THRESHOLD")
    ops_archive_stale_minutes: int = Field(default=10, ge=1, alias="OPS_ARCHIVE_STALE_MINUTES")
    ops_callback_stale_minutes: int = Field(default=1440, ge=1, alias="OPS_CALLBACK_STALE_MINUTES")
    ops_backup_dir: str = Field(default="./storage/backups", alias="OPS_BACKUP_DIR")
    ops_backup_stale_hours: int = Field(default=26, ge=1, alias="OPS_BACKUP_STALE_HOURS")
    ops_backup_retention_days: int = Field(default=14, ge=1, alias="OPS_BACKUP_RETENTION_DAYS")
    ops_disk_free_min_gb: float = Field(default=2.0, ge=0, alias="OPS_DISK_FREE_MIN_GB")
    ops_alert_group_id: str | None = Field(default=None, alias="OPS_ALERT_GROUP_ID")
    ops_alert_user_ids: str = Field(default="", alias="OPS_ALERT_USER_IDS")

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

    @property
    def legal_data_retention_status_list(self) -> list[str]:
        allowed = {"rejected", "approved", "corrected", "not_required"}
        return [
            status
            for status in (item.strip() for item in self.legal_data_retention_review_statuses.split(","))
            if status in allowed
        ]

    @property
    def merchant_workday_list(self) -> list[int]:
        values: list[int] = []
        for item in self.merchant_workdays.split(","):
            try:
                value = int(item.strip())
            except ValueError:
                continue
            if 0 <= value <= 6 and value not in values:
                values.append(value)
        return values or [0, 1, 2, 3, 4]


@lru_cache
def get_settings() -> Settings:
    return Settings()
