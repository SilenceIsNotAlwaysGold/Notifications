from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


KDocsTarget = Literal["enforcement", "court", "payment", "repayment"]


class KDocsTargetOut(BaseModel):
    key: KDocsTarget
    name: str
    configured: bool
    file_id: str | None
    worksheet_id: int
    sheet_name: str | None = None
    total_rows: int = 0


class KDocsBrowserOverviewOut(BaseModel):
    mode: str
    transport: str
    configured: bool
    drive_id: str | None
    targets: list[KDocsTargetOut]


class KDocsRowOut(BaseModel):
    row_index: int
    row_version: str
    values: dict[str, Any]


class KDocsRowUpdate(BaseModel):
    row_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    values: dict[str, Any] = Field(min_length=1, max_length=25)

    @model_validator(mode="after")
    def validate_cell_values(self):
        for key, value in self.values.items():
            if len(key) > 64:
                raise ValueError("字段名过长")
            if isinstance(value, (dict, list, tuple, set)):
                raise ValueError(f"{key} 只支持单元格值")
            if len(str(value or "")) > 5000:
                raise ValueError(f"{key} 内容不能超过 5000 字")
        return self


class KDocsRowMutationOut(BaseModel):
    target: KDocsTarget
    target_name: str
    row_index: int
    row_number: int
    values: dict[str, Any]
    row_version: str | None = None


class KDocsRowPageOut(BaseModel):
    target: KDocsTarget
    target_name: str
    file_id: str
    worksheet_id: int
    sheet_name: str
    file_url: str | None = None
    headers: list[str]
    total: int
    page: int
    page_size: int
    query: str = ""
    filter_column: str = ""
    filter_value: str = ""
    sort_column: str = ""
    court_mode: str = ""
    date_from: str | None = None
    date_to: str | None = None
    sort_order: str = "asc"
    items: list[KDocsRowOut]


class KDocsDocumentOut(BaseModel):
    file_id: str
    name: str
    path: str | None = None
    size: int | None = None
    modified_at: str | None = None
    modified_by: str | None = None
    url: str | None = None


class KDocsDocumentPageOut(BaseModel):
    query: str
    page_size: int
    next_page_token: str | None = None
    items: list[KDocsDocumentOut] = Field(default_factory=list)
