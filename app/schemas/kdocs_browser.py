from typing import Any, Literal

from pydantic import BaseModel, Field


KDocsTarget = Literal["enforcement", "court", "payment"]


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
    values: dict[str, Any]


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
