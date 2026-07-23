from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiResponse(BaseModel):
    code: int = 0
    message: str
    data: Any | None = None


class CaseCreate(BaseModel):
    case_no: str
    debtor_name: str
    tenant_id: str | None = None
    group_id: str
    debtor_wecom_userid: str | None = None
    lawyer_wecom_userid: str | None = None
    due_date: date
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    plaintiff_name: str | None = Field(default=None, max_length=255)
    court_name: str | None = Field(default=None, max_length=255)
    document_type: str | None = Field(default=None, max_length=64)
    filing_date: date | None = None
    enforcement_case_no: str | None = Field(default=None, max_length=128)
    responsible_contact_id: int | None = None
    lifecycle_stage: str = Field(default="active", max_length=32)
    source: str = Field(default="manual", max_length=32)


class CaseUpdate(BaseModel):
    debtor_name: str | None = Field(default=None, min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)
    group_id: str | None = Field(default=None, min_length=1, max_length=128)
    debtor_wecom_userid: str | None = Field(default=None, max_length=128)
    lawyer_wecom_userid: str | None = Field(default=None, max_length=128)
    due_date: date | None = None
    total_amount: Decimal | None = Field(default=None, ge=0)
    plaintiff_name: str | None = Field(default=None, max_length=255)
    court_name: str | None = Field(default=None, max_length=255)
    document_type: str | None = Field(default=None, max_length=64)
    filing_date: date | None = None
    enforcement_case_no: str | None = Field(default=None, max_length=128)
    responsible_contact_id: int | None = None
    lifecycle_stage: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class CaseOut(BaseModel):
    id: int
    case_no: str
    debtor_name: str
    tenant_id: str | None
    group_id: str
    debtor_wecom_userid: str | None
    lawyer_wecom_userid: str | None
    due_date: date
    status: str
    total_amount: Decimal
    paid_amount: Decimal
    plaintiff_name: str | None
    court_name: str | None
    document_type: str | None
    filing_date: date | None
    enforcement_case_no: str | None
    responsible_contact_id: int | None
    lifecycle_stage: str
    source: str
    extra_identifiers_json: str
    overdue_at: datetime | None
    defaulted_at: datetime | None
    paid_at: datetime | None
    last_status_checked_at: datetime | None
    repayment_reminder_created_at: datetime | None
    default_upgrade_reminder_created_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseListOut(BaseModel):
    total: int
    items: list[CaseOut]


class CaseCandidateOut(BaseModel):
    id: int
    case_no: str
    tenant_id: str | None
    group_id: str
    debtor_name: str | None
    due_date: date | None
    total_amount: Decimal | None
    document_type: str | None
    confidence: Decimal | None
    source_type: str
    source_message_id: int | None
    source_media_file_id: int | None
    status: str
    occurrence_count: int
    confirmed_case_id: int | None
    first_detected_at: datetime
    last_detected_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseCandidateListOut(BaseModel):
    total: int
    items: list[CaseCandidateOut]


class CaseCandidateScanOut(BaseModel):
    scanned_media: int
    scanned_messages: int
    created_candidates: int


class CaseCandidateConfirm(BaseModel):
    debtor_name: str = Field(min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, max_length=128)
    group_id: str = Field(min_length=1, max_length=128)
    debtor_wecom_userid: str | None = Field(default=None, max_length=128)
    lawyer_wecom_userid: str | None = Field(default=None, max_length=128)
    due_date: date
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=0)


class CaseCandidateConfirmOut(BaseModel):
    candidate: CaseCandidateOut
    case: CaseOut
    linked_media_files: int = 0
    linked_events: int = 0
    updated_group_messages: int = 0
    backfill_skipped_reason: str | None = None


class CaseUpdateOut(BaseModel):
    case: CaseOut
    updated_pending_reminders: int = 0
    linked_media_files: int = 0
    linked_events: int = 0
    updated_group_messages: int = 0
    backfill_skipped_reason: str | None = None


class CaseLifecycleScanOut(BaseModel):
    checked: int
    created_repayment_reminders: int
    marked_overdue: int
    marked_defaulted: int
    marked_paid: int
    created_default_upgrade_reminders: int
    synced_status: int
    scoped: bool = False
    allowed_group_count: int = 0
    allowed_case_count: int = 0
    allowed_tenant_count: int = 0


class MockMessageCreate(BaseModel):
    tenant_id: str | None = None
    group_id: str
    sender_id: str
    msg_type: str = Field(pattern="^(text|image|file|pdf|link|unknown)$")
    content: str | None = None
    file_url: str | None = None
    received_at: datetime | None = None
    raw_payload_json: dict[str, Any] | None = None


class MessageProcessOut(BaseModel):
    group_message_id: int
    case_id: int | None
    event_ids: list[int]
    reminder_ids: list[int]
    extracted: dict[str, Any]


class CustomReminderCreate(BaseModel):
    tenant_id: str | None = None
    group_id: str
    remind_at: datetime
    content: str
    target_userid: str | None = None
    case_id: int | None = None


class CustomReminderUpdate(BaseModel):
    remind_at: datetime | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    target_userid: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class ReminderCancel(BaseModel):
    reason: str = Field(default="人工取消", min_length=1, max_length=1000)


class ReminderOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int | None
    group_id: str
    reminder_type: str
    remind_at: datetime
    content: str
    target_userid: str | None
    target_contact_id: int | None
    rule_id: int | None
    source_event_id: int | None
    dedupe_key: str | None
    status: str
    retry_count: int
    last_error: str | None
    sent_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReminderListOut(BaseModel):
    total: int
    items: list[ReminderOut]


class RunDueOut(BaseModel):
    sent: int
    simulated: int = 0
    failed: int
    retrying: int
    total: int


class ReminderRuleCreate(BaseModel):
    tenant_id: str | None = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    rule_type: Literal["repayment", "default_upgrade", "payment_tracking"]
    offset_days: int = Field(ge=0, le=365)
    send_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    target_role: Literal["debtor", "lawyer", "both"] = "lawyer"
    template: str = Field(min_length=1, max_length=4000)
    sort_order: int = Field(default=0, ge=0, le=10000)
    enabled: bool = True


class ReminderRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    rule_type: Literal["repayment", "default_upgrade", "payment_tracking"] | None = None
    offset_days: int | None = Field(default=None, ge=0, le=365)
    send_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    target_role: Literal["debtor", "lawyer", "both"] | None = None
    template: str | None = Field(default=None, min_length=1, max_length=4000)
    sort_order: int | None = Field(default=None, ge=0, le=10000)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class ReminderRuleOut(BaseModel):
    id: int
    tenant_id: str | None
    name: str
    rule_type: str
    offset_days: int
    send_time: str
    target_role: str
    template: str
    sort_order: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReminderRuleListOut(BaseModel):
    total: int
    items: list[ReminderRuleOut]


class EventOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int | None
    group_message_id: int | None
    event_type: str
    event_time: datetime | None
    amount: Decimal | None
    extracted_text: str | None
    metadata_json: str
    attribution_status: str
    business_status: str
    confidence: Decimal | None
    approved_by: str | None
    approved_at: datetime | None
    rejected_reason: str | None
    applied_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EventListOut(BaseModel):
    total: int
    items: list[EventOut]


class DocumentSyncLogOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int | None
    sync_type: str
    sync_target: str | None
    external_doc_id: str | None
    external_sheet_name: str | None
    external_row_key: str | None
    external_row_index: int | None
    transport_mode: str | None
    mapping_version: str
    outcome: str
    readback_payload_json: str | None
    idempotency_key: str | None
    request_payload_json: str
    response_payload_json: str
    status: str
    error_message: str | None
    retry_count: int
    last_attempt_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentSyncLogListOut(BaseModel):
    total: int
    items: list[DocumentSyncLogOut]


class WeComArchiveReplayRequest(BaseModel):
    messages: list[dict[str, Any]]


class WeComArchiveReplayWithOcrRequest(BaseModel):
    messages: list[dict[str, Any]]
    ocr_text_by_msgid: dict[str, str] = Field(default_factory=dict)


class WeComArchivePullOut(BaseModel):
    pulled: int
    processed: int
    failed: int
    skipped: int = 0
    discovered: int = 0
    identified: int = 0
    last_seq: int


class WeComArchiveGroupCreate(BaseModel):
    room_id: str = Field(min_length=1, max_length=128)
    wecomapi_room_id: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=128)
    status: Literal["discovered", "enabled", "disabled"] = "enabled"
    group_type: Literal["merchant", "debtor", "internal", "other"] = "other"
    features: dict[str, bool] = Field(default_factory=dict)
    internal_userids: list[str] = Field(default_factory=list)
    alert_userids: list[str] = Field(default_factory=list)
    question_timeout_minutes: int = Field(default=5, ge=1, le=1440)


class WeComArchiveGroupUpdate(BaseModel):
    wecomapi_room_id: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=128)
    status: Literal["discovered", "enabled", "disabled"] | None = None
    group_type: Literal["merchant", "debtor", "internal", "other"] | None = None
    features: dict[str, bool] | None = None
    internal_userids: list[str] | None = None
    alert_userids: list[str] | None = None
    question_timeout_minutes: int | None = Field(default=None, ge=1, le=1440)


class WeComArchiveGroupOut(BaseModel):
    id: int
    room_id: str
    wecomapi_room_id: str | None
    display_name: str | None
    tenant_id: str | None
    status: str
    group_type: str
    features: dict[str, bool] = Field(default_factory=dict)
    internal_userids: list[str] = Field(default_factory=list)
    alert_userids: list[str] = Field(default_factory=list)
    question_timeout_minutes: int
    seen_message_count: int
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        data = super().model_validate(obj, *args, **kwargs)
        if hasattr(obj, "features_json"):
            import json

            data.features = json.loads(obj.features_json or "{}")
            data.internal_userids = json.loads(obj.internal_userids_json or "[]")
            data.alert_userids = json.loads(obj.alert_userids_json or "[]")
        return data


class WeComArchiveGroupListOut(BaseModel):
    total: int
    items: list[WeComArchiveGroupOut]


class MerchantQuestionOut(BaseModel):
    id: int
    tenant_id: str | None
    group_id: str
    group_message_id: int
    sender_id: str
    content: str
    asked_at: datetime
    deadline_at: datetime
    status: str
    reply_message_id: int | None
    replied_at: datetime | None
    reminder_id: int | None
    assigned_userid: str | None
    closed_by: str | None
    closed_at: datetime | None
    close_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MerchantQuestionListOut(BaseModel):
    total: int
    items: list[MerchantQuestionOut]


class MerchantQuestionClose(BaseModel):
    reason: str = Field(default="人工关闭", min_length=1, max_length=1000)


class WeComArchiveReplayWithOcrOut(WeComArchivePullOut):
    ocr_processed: int = 0
    ocr_failed: int = 0
    ocr_results: list[dict[str, Any]] = Field(default_factory=list)


class WeComArchiveDemoReplayOut(WeComArchiveReplayWithOcrOut):
    case_id: int
    case_no: str


class MediaFileOut(BaseModel):
    id: int
    tenant_id: str | None
    group_message_id: int | None
    case_id: int | None
    group_id: str
    msg_id: str | None
    seq: int | None
    media_type: str
    original_filename: str | None
    file_ext: str | None
    mime_type: str | None
    file_size: int | None
    md5sum: str | None
    source: str
    source_payload_json: str | None
    local_path: str | None
    public_url: str | None
    download_status: str
    ocr_status: str
    extracted_text: str | None
    metadata_json: str | None
    review_status: str
    review_event_id: int | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    business_applied_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MediaFileListOut(BaseModel):
    total: int
    items: list[MediaFileOut]


class MediaOCRResultOut(BaseModel):
    media_file_id: int
    ocr_status: str
    event_id: int | None = None
    matched_case_id: int | None = None
    event_type: str | None = None
    amount: str | None = None
    document_type: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    court_time: str | None = None
    requires_review: bool = False
    extraction_confidence: float | None = None
    review_reasons: list[str] = Field(default_factory=list)
    parser: str | None = None
    llm_status: str | None = None
    created_reminders: int = 0
    review_status: str = "not_required"
    business_applied: bool = False


class OCRReviewDecision(BaseModel):
    decision: Literal["approved", "corrected", "rejected"]
    note: str | None = Field(default=None, max_length=1000)
    case_no: str | None = Field(default=None, max_length=128)
    event_type: Literal[
        "judgment",
        "court_notice",
        "payment_notice",
        "payment_screenshot",
        "keyword",
        "unknown",
    ] | None = None
    document_type: Literal["判决书", "调解书", "裁定书", "开庭传票"] | None = None
    plaintiff: str | None = Field(default=None, max_length=255)
    defendant: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0)
    court_time: datetime | None = None

    @model_validator(mode="after")
    def validate_decision(self):
        correction_fields = {
            "case_no",
            "event_type",
            "document_type",
            "plaintiff",
            "defendant",
            "amount",
            "court_time",
        }
        if self.decision == "corrected" and not (self.model_fields_set & correction_fields):
            raise ValueError("修正复核至少需要修改一个识别字段")
        if self.decision == "rejected" and not (self.note or "").strip():
            raise ValueError("驳回复核必须填写备注")
        return self


class OCRReviewOut(BaseModel):
    media_file_id: int
    tenant_id: str | None
    case_id: int | None
    group_id: str
    msg_id: str | None
    media_type: str
    original_filename: str | None
    mime_type: str | None
    ocr_status: str
    review_status: str
    event_id: int | None
    extracted_text: str | None
    context_messages: list[dict[str, Any]] = Field(default_factory=list)
    ocr_result: dict[str, Any]
    final_result: dict[str, Any] | None
    preview_url: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    business_applied_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OCRReviewListOut(BaseModel):
    total: int
    items: list[OCRReviewOut]


class OCRReviewDecisionOut(BaseModel):
    review: OCRReviewOut
    already_decided: bool = False
    created_reminders: int = 0
    cancelled_reminders: int = 0


class SystemRunLogOut(BaseModel):
    id: int
    tenant_id: str | None
    run_type: str
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    total_count: int
    success_count: int
    failed_count: int
    summary_json: str | None
    error_message: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemRunLogListOut(BaseModel):
    total: int
    items: list[SystemRunLogOut]


class CaseStatusHistoryOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int
    old_status: str | None
    new_status: str
    reason: str | None
    changed_by: str
    before_json: str | None
    after_json: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseStatusHistoryListOut(BaseModel):
    total: int
    items: list[CaseStatusHistoryOut]


class ReminderSendLogOut(BaseModel):
    id: int
    tenant_id: str | None
    reminder_id: int
    group_id: str
    target_userid: str | None
    send_mode: str
    status: str
    request_payload_json: str | None
    response_payload_json: str | None
    error_message: str | None
    attempt_no: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReminderSendLogListOut(BaseModel):
    total: int
    items: list[ReminderSendLogOut]


class OperationAuditLogOut(BaseModel):
    id: int
    tenant_id: str | None
    operator: str | None
    auth_type: str | None
    operator_role: str | None
    api_key_id: int | None
    api_key_prefix: str | None
    action: str
    method: str
    path: str
    status_code: int | None
    request_summary_json: str | None
    response_summary_json: str | None
    resource_scope_json: str | None
    client_host: str | None
    user_agent: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OperationAuditLogListOut(BaseModel):
    total: int
    items: list[OperationAuditLogOut]


class ApiKeyCreate(BaseModel):
    name: str | None = None
    role: str
    allowed_group_ids: list[str] = Field(default_factory=list)
    allowed_case_ids: list[int] = Field(default_factory=list)
    allowed_tenant_ids: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None
    allowed_group_ids: list[str] | None = None
    allowed_case_ids: list[int] | None = None
    allowed_tenant_ids: list[str] | None = None


class ApiKeyOut(BaseModel):
    id: int
    key_prefix: str
    name: str | None
    role: str
    is_active: bool
    allowed_group_ids: list[str] = Field(default_factory=list)
    allowed_case_ids: list[int] = Field(default_factory=list)
    allowed_tenant_ids: list[str] = Field(default_factory=list)
    expires_at: datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        data = super().model_validate(obj, *args, **kwargs)
        if hasattr(obj, "allowed_group_ids_json"):
            import json

            data.allowed_group_ids = json.loads(obj.allowed_group_ids_json or "[]")
            data.allowed_case_ids = json.loads(obj.allowed_case_ids_json or "[]")
            data.allowed_tenant_ids = json.loads(obj.allowed_tenant_ids_json or "[]")
        return data


class ApiKeyCreateOut(ApiKeyOut):
    api_key: str


class ApiKeyListOut(BaseModel):
    total: int
    items: list[ApiKeyOut]


class TenantCreate(BaseModel):
    tenant_id: str
    tenant_name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    remark: str | None = None


class TenantUpdate(BaseModel):
    tenant_name: str | None = None
    status: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    remark: str | None = None


class TenantOut(BaseModel):
    id: int
    tenant_id: str
    tenant_name: str
    status: str
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantListOut(BaseModel):
    total: int
    items: list[TenantOut]


class TenantSettingsIn(BaseModel):
    wecom_send_mode: Literal["mock", "wecomapi"] | None = None
    wecom_timeout_seconds: int | None = None
    wecom_max_retry: int | None = None
    tencent_doc_mode: str | None = None
    tencent_doc_base_url: str | None = None
    tencent_doc_access_token: str | None = None
    tencent_doc_sheet_id: str | None = None
    tencent_doc_case_sheet_name: str | None = None
    tencent_doc_archive_sheet_name: str | None = None
    tencent_doc_case_no_column: str | None = None
    tencent_doc_status_column: str | None = None
    tencent_doc_paid_amount_column: str | None = None
    tencent_doc_timeout_seconds: int | None = None
    ocr_provider: str | None = None
    ocr_enable_reprocess: bool | None = None
    ocr_max_text_length: int | None = None
    repayment_reminder_days_before: int | None = None
    default_upgrade_days_after_overdue: int | None = None
    case_status_scan_enabled: bool | None = None
    keyword_config: dict[str, list[str]] | None = None
    feature_flags: dict[str, bool] | None = None


class TenantSettingsOut(BaseModel):
    tenant_id: str
    source: str
    wecom_send_mode: str | None
    wecom_timeout_seconds: int | None
    wecom_max_retry: int | None
    tencent_doc_mode: str | None
    tencent_doc_base_url: str | None
    has_tencent_doc_access_token: bool
    tencent_doc_access_token: str | None
    tencent_doc_sheet_id: str | None
    tencent_doc_case_sheet_name: str | None
    tencent_doc_archive_sheet_name: str | None
    tencent_doc_case_no_column: str | None
    tencent_doc_status_column: str | None
    tencent_doc_paid_amount_column: str | None
    tencent_doc_timeout_seconds: int | None
    ocr_provider: str | None
    ocr_enable_reprocess: bool | None
    ocr_max_text_length: int | None
    repayment_reminder_days_before: int | None
    default_upgrade_days_after_overdue: int | None
    case_status_scan_enabled: bool | None
    keyword_config: dict[str, list[str]]
    feature_flags: dict[str, bool]


class EffectiveTenantSettingsOut(BaseModel):
    tenant_id: str | None
    source: str
    wecom: dict[str, Any]
    tencent_doc: dict[str, Any]
    ocr: dict[str, Any]
    reminder: dict[str, Any]
    feature_flags: dict[str, bool]
    keyword_config: dict[str, list[str]]


class WeComArchiveCheckIn(BaseModel):
    corp_id: str | None = None
    archive_secret: str | None = None
    private_key: str | None = None
    private_key_path: str | None = None
    public_key_ver: str | None = None
    sidecar_url: str | None = None


class WeComArchiveCheckOut(BaseModel):
    ready: bool
    missing_fields: list[str]
    warnings: list[str]


class SystemAlertOut(BaseModel):
    id: int
    tenant_id: str | None
    alert_type: str
    severity: str
    source: str
    status: str
    title: str
    message: str
    details_json: str
    occurrence_count: int
    first_detected_at: datetime
    last_detected_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemAlertListOut(BaseModel):
    total: int
    items: list[SystemAlertOut]
