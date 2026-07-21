from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AndroidTapRequest(BaseModel):
    x: int = Field(ge=0, le=8192)
    y: int = Field(ge=0, le=8192)


class AndroidSwipeRequest(BaseModel):
    start_x: int = Field(ge=0, le=8192)
    start_y: int = Field(ge=0, le=8192)
    end_x: int = Field(ge=0, le=8192)
    end_y: int = Field(ge=0, le=8192)
    duration_ms: int = Field(default=300, ge=100, le=3000)


class AndroidTextRequest(BaseModel):
    input_text: str = Field(min_length=1, max_length=256)

    @field_validator("input_text")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("输入内容不能包含控制字符")
        return value


class AndroidKeyeventRequest(BaseModel):
    key: Literal["back", "home", "recent", "enter", "delete"]
