from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class RecognitionSettingsOut(BaseModel):
    ocr_provider: Literal["mock", "local_text", "tencent", "aliyun"]
    ocr_sidecar_url: str | None
    has_tencent_secret_id: bool
    has_tencent_secret_key: bool
    secret_mask: str
    tencent_region: str
    tencent_pdf_max_pages: int
    extraction_mode: Literal["regex", "llm"]
    llm_base_url: str | None
    has_llm_api_key: bool
    llm_model: str | None
    llm_timeout_seconds: int
    llm_max_text_length: int
    llm_min_confidence: float
    llm_fallback_to_regex: bool
    data_retention_enabled: bool
    data_retention_days: int
    data_retention_review_statuses: list[str]


class RecognitionSettingsUpdate(BaseModel):
    ocr_provider: Literal["mock", "local_text", "tencent", "aliyun"] | None = None
    ocr_sidecar_url: str | None = Field(default=None, max_length=255)
    tencent_pdf_max_pages: int | None = Field(default=None, ge=1, le=20)
    extraction_mode: Literal["regex", "llm"] | None = None
    llm_base_url: str | None = Field(default=None, max_length=255)
    llm_api_key: str | None = Field(default=None, max_length=512)
    llm_model: str | None = Field(default=None, max_length=128)
    llm_timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    llm_max_text_length: int | None = Field(default=None, ge=1000, le=100000)
    llm_min_confidence: float | None = Field(default=None, ge=0, le=1)
    llm_fallback_to_regex: bool | None = None
    data_retention_enabled: bool | None = None
    data_retention_days: int | None = Field(default=None, ge=30, le=36500)
    data_retention_review_statuses: list[Literal["rejected", "approved", "corrected", "not_required"]] | None = Field(default=None, min_length=1)

    @field_validator(
        "ocr_sidecar_url",
        "llm_base_url",
        "llm_api_key",
        "llm_model",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise ValueError("配置值不能包含控制字符")
        return cleaned

    @field_validator("ocr_sidecar_url", "llm_base_url")
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("接口地址必须是有效的 HTTP(S) URL，且不能包含账号密码")
        return value.rstrip("/")

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class RecognitionServiceStatus(BaseModel):
    configured: bool
    available: bool
    message: str
    endpoint: str | None = None


class RecognitionCheckOut(BaseModel):
    ocr: RecognitionServiceStatus
    llm: RecognitionServiceStatus
