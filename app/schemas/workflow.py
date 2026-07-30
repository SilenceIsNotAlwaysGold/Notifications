from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CaseGroupCreate(BaseModel):
    case_id: int
    group_id: str = Field(min_length=1, max_length=128)
    is_primary: bool = False


class CaseGroupOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int
    group_id: str
    is_primary: bool
    status: str
    source: str
    confirmed_by: str | None
    confirmed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttributionOut(BaseModel):
    id: int
    tenant_id: str | None
    group_id: str
    subject_type: str
    subject_id: int
    media_file_id: int | None
    event_id: int | None
    suggested_case_id: int | None
    assigned_case_id: int | None
    confidence: int | None
    reason: str | None
    evidence_json: str
    status: str
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime
    group_name: str | None = None
    source_message_id: int | None = None
    source_sender_id: str | None = None
    source_received_at: datetime | None = None
    source_text: str | None = None
    media_type: str | None = None
    mime_type: str | None = None
    original_filename: str | None = None
    preview_url: str | None = None
    ocr_text: str | None = None
    ocr_status: str | None = None
    review_status: str | None = None
    event_type: str | None = None
    amount: Decimal | None = None
    recognized_fields: dict[str, Any] = Field(default_factory=dict)
    field_sources: dict[str, Any] = Field(default_factory=dict)
    context_messages: list[dict[str, Any]] = Field(default_factory=list)
    suggested_case_no: str | None = None
    suggested_case_party: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AttributionListOut(BaseModel):
    total: int
    items: list[AttributionOut]


class AttributionBatchDecision(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=500)
    case_id: int | None = None
    decision: Literal["confirm", "reject"] = "confirm"
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_decision(self):
        if self.decision == "confirm" and self.case_id is None:
            raise ValueError("确认归属必须选择案件")
        if self.decision == "reject" and not (self.reason or "").strip():
            raise ValueError("驳回归属必须填写原因")
        return self


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    applies_to_event_id: int | None = Field(default=None, ge=1)
    payment_date: date | None = None
    payer_name: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1000)
    status: Literal["pending", "approved"] = "pending"


class PaymentUpdate(BaseModel):
    action: Literal["approve", "reverse"]
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def reversal_note(self):
        if self.action == "reverse" and not (self.note or "").strip():
            raise ValueError("冲正必须填写原因")
        return self


class PaymentOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int
    source_event_id: int | None
    applies_to_event_id: int | None
    source_media_file_id: int | None
    record_type: str
    amount: Decimal
    payment_date: date | None
    payer_name: str | None
    credential_fingerprint: str | None
    status: str
    reversal_of_id: int | None
    note: str | None
    approved_by: str | None
    approved_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentListOut(BaseModel):
    total: int
    items: list[PaymentOut]


class PaymentTrackingOut(BaseModel):
    event_id: int
    case_id: int | None
    business_status: str
    confidence: Decimal | None
    automation_outcome: str | None = None
    automation_threshold: float | None = None
    review_reasons: list[str] = Field(default_factory=list)
    source_group_id: str | None = None
    source_group_name: str | None = None
    source_sender_id: str | None = None
    notice_date: date
    plaintiff: str | None
    defendant: str | None
    case_no: str | None
    payment_info: str | None
    payment_type: str
    required_amount: Decimal | None
    paid_amount: Decimal
    outstanding_amount: Decimal | None
    payment_status: str
    tracking_status: str
    payment_deadline: date | None
    remaining_payment_time: str
    screenshot_media_file_id: int | None
    screenshot_url: str | None
    notice_screenshot_url: str | None
    receipt_urls: list[str]


class PaymentReceiptOut(BaseModel):
    id: int
    case_id: int
    source_event_id: int | None
    source_media_file_id: int | None
    amount: Decimal
    payment_date: date | None
    payer_name: str | None
    case_no: str
    plaintiff: str | None
    defendant: str
    screenshot_url: str | None


class PaymentReceiptListOut(BaseModel):
    total: int
    items: list[PaymentReceiptOut]


class PaymentReceiptAssignment(BaseModel):
    payment_id: int = Field(ge=1)


class PaymentMediaReceiptAssignment(BaseModel):
    media_file_id: int = Field(ge=1)


class PaymentTextConfirmationAssignment(BaseModel):
    confirmation_event_id: int = Field(ge=1)


class UnmatchedPaymentMediaOut(BaseModel):
    media_file_id: int
    event_id: int
    group_id: str
    group_name: str | None
    amount: Decimal | None
    defendant: str | None
    case_no: str | None
    preview_url: str | None
    candidate_event_ids: list[int] = Field(default_factory=list)
    created_at: datetime


class UnmatchedPaymentMediaListOut(BaseModel):
    total: int
    items: list[UnmatchedPaymentMediaOut]


class PaymentNoticeCandidateOut(BaseModel):
    event_id: int
    defendant: str | None
    case_no: str | None
    payment_type: str
    amount: Decimal | None
    notice_date: date
    source_text: str | None
    match_score: int


class UnmatchedPaymentTextConfirmationOut(BaseModel):
    event_id: int
    group_id: str
    group_name: str | None
    sender_id: str
    confirmation_text: str
    amount: Decimal | None
    defendant: str | None
    case_no: str | None
    confidence: Decimal | None
    automation_outcome: str | None = None
    automation_threshold: float | None = None
    review_reasons: list[str] = Field(default_factory=list)
    candidates: list[PaymentNoticeCandidateOut] = Field(default_factory=list)
    received_at: datetime


class UnmatchedPaymentTextConfirmationListOut(BaseModel):
    total: int
    items: list[UnmatchedPaymentTextConfirmationOut]


class PaymentTrackingListOut(BaseModel):
    total: int
    items: list[PaymentTrackingOut]


class PaymentDailySummaryOut(BaseModel):
    summary_date: date
    confirmed_count: int
    pending_count: int
    content: str


class EventDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ContactOut(BaseModel):
    id: int
    tenant_id: str | None
    display_name: str
    role: str
    archive_user_id: str | None
    wecomapi_user_id: str | None
    source: str
    is_active: bool
    membership_status: str
    membership_source: str
    last_seen_at: datetime


class GroupContactListOut(BaseModel):
    group_id: str
    inventory_source: str
    warning: str | None
    items: list[ContactOut]


class KDocsReconciliationOut(BaseModel):
    id: int
    tenant_id: str | None
    case_id: int | None
    sync_log_id: int | None
    target: str
    external_row_index: int | None
    status: str
    expected_json: str
    actual_json: str
    differences_json: str
    checked_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KDocsReconciliationListOut(BaseModel):
    total: int
    items: list[KDocsReconciliationOut]


class CaseWorkspaceOut(BaseModel):
    case: dict[str, Any]
    groups: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    media: list[dict[str, Any]]
    events: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    reminders: list[dict[str, Any]]
    sync_logs: list[dict[str, Any]]
    audit_timeline: list[dict[str, Any]]
    counts: dict[str, int]
