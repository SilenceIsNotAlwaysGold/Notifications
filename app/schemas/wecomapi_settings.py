from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


WeComSendMode = Literal["mock", "wecomapi"]


class WeComApiSettingsOut(BaseModel):
    send_mode: WeComSendMode
    base_url: str | None
    api_path: str
    token_header: str
    has_token: bool
    token_mask: str | None
    guid: str | None
    has_guid: bool
    callback_url: str
    callback_auth_enabled: bool
    platform_url: str
    login_managed_by: Literal["third_party_platform"] = "third_party_platform"


class WeComApiSettingsUpdate(BaseModel):
    send_mode: WeComSendMode | None = None
    base_url: str | None = Field(default=None, max_length=255)
    api_path: str | None = Field(default=None, max_length=128)
    token_header: str | None = Field(default=None, max_length=64)
    token: str | None = Field(default=None, max_length=512)
    guid: str | None = Field(default=None, max_length=128)

    @field_validator("base_url", "api_path", "token_header", "token", "guid")
    @classmethod
    def reject_control_chars(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise ValueError("配置值不能包含控制字符")
        return cleaned

    @field_validator("api_path")
    @classmethod
    def validate_api_path(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        return "/" + value.lstrip("/")

    @field_validator("token_header")
    @classmethod
    def validate_token_header(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if not value.replace("-", "").isalnum():
            raise ValueError("Token Header 只能包含字母、数字和连字符")
        return value

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个待更新字段")
        return self


class WeComApiLoginStatusOut(BaseModel):
    configured: bool
    online: bool
    stage: str
    missing: list[str] = Field(default_factory=list)
    account_name: str | None = None
    vendor_code: int | str | None = None
    vendor_message: str | None = None
    checked_endpoint: str | None = None
    raw_data: dict[str, Any] | None = None


class WeComApiRoomOut(BaseModel):
    room_id: str
    room_name: str | None = None
    owner_userid: str | None = None
    member_count: int | None = None
    avatar_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class WeComApiGroupSyncOut(BaseModel):
    fetched: int
    mapped: int
    updated: int
    rooms: list[WeComApiRoomOut]


class WeComApiGroupMemberOut(BaseModel):
    user_id: str
    display_name: str


class WeComApiGroupMembersOut(BaseModel):
    room_id: str
    room_name: str | None = None
    members: list[WeComApiGroupMemberOut]
    warning: str | None = None


class WeComApiTestSendRequest(BaseModel):
    room_id: str = Field(min_length=1, max_length=128)
    content: str = Field(default="【致和法务】企业微信发送通道测试成功。", min_length=1, max_length=500)

    @field_validator("room_id", "content")
    @classmethod
    def strip_test_send_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("测试发送字段不能为空")
        return cleaned
