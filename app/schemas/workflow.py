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
