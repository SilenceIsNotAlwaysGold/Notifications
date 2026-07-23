from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.adapters.kdocs_mcp import KDocsMcpClient
from app.core.config import Settings, get_settings
from app.schemas.kdocs_browser import (
    KDocsBrowserOverviewOut,
    KDocsDocumentOut,
    KDocsDocumentPageOut,
    KDocsRowOut,
    KDocsRowPageOut,
    KDocsTarget,
    KDocsTargetOut,
)
from app.utils.datetime_utils import app_timezone


@dataclass(frozen=True)
class TargetDefinition:
    key: KDocsTarget
    name: str
    file_id_setting: str
    worksheet_id_setting: str
    headers: tuple[str, ...]


TARGETS: dict[KDocsTarget, TargetDefinition] = {
    "enforcement": TargetDefinition(
        key="enforcement",
        name="强制执行进度",
        file_id_setting="kdocs_enforcement_file_id",
        worksheet_id_setting="kdocs_enforcement_worksheet_id",
        headers=(
            "代理人", "（法院组）代提交人", "原告主体", "被告", "身份证", "文书执行类型", "上传文件",
            "文书签发时间", "应还款时间", "履约情况", "提交情况", "申请强制时间", "所提交的法院",
            "法院审核状态", "审核意见", "材料是否寄出", "物流单号", "执行案号", "民初案号", "总金额",
            "已还欠款", "法官电话", "案件状态", "备注", "订单号",
        ),
    ),
    "court": TargetDefinition(
        key="court",
        name="开庭时间",
        file_id_setting="kdocs_court_time_file_id",
        worksheet_id_setting="kdocs_court_time_worksheet_id",
        headers=(
            "法院", "开庭时间", "时间", "公司（原告）", "民初案号", "被告", "开庭方式", "跟进人", "交付时间",
            "回收时间", "代开庭邮寄单号", "金额", "代办事务", "代理人", "备注", "承办法官电话", "传票", "核对",
        ),
    ),
    "payment": TargetDefinition(
        key="payment",
        name="缴费登记",
        file_id_setting="kdocs_payment_file_id",
        worksheet_id_setting="kdocs_payment_worksheet_id",
        headers=("案号", "被告", "缴费类型", "金额", "文件链接", "识别摘要", "需人工复核", "消息ID"),
    ),
}


class KDocsBrowserService:
    def __init__(self, settings: Settings | None = None, client: KDocsMcpClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or KDocsMcpClient(self.settings)

    def overview(self) -> KDocsBrowserOverviewOut:
        targets = [self._target_overview(definition) for definition in TARGETS.values()]
        configured = (
            self.settings.kdocs_mode == "real"
            and self.settings.kdocs_transport == "mcp"
            and bool(self.settings.kdocs_access_token and self.settings.kdocs_drive_id)
            and all(target.configured for target in targets)
        )
        return KDocsBrowserOverviewOut(
            mode=self.settings.kdocs_mode,
            transport=self.settings.kdocs_transport,
            configured=configured,
            drive_id=self.settings.kdocs_drive_id,
            targets=targets,
        )

    def list_rows(self, target: KDocsTarget, page: int, page_size: int) -> KDocsRowPageOut:
        self._ensure_real_mcp()
        definition = TARGETS[target]
        file_id = str(getattr(self.settings, definition.file_id_setting) or "")
        worksheet_id = int(getattr(self.settings, definition.worksheet_id_setting))
        if not file_id:
            raise ValueError(f"{definition.name}尚未配置 file_id")
        sheet = self.client.get_sheet_info(file_id, worksheet_id)
        last_row = max(int(sheet.get("rowTo") or 0), 0)
        total = last_row
        row_from = (page - 1) * page_size + 1
        row_to = min(row_from + page_size - 1, last_row)
        cells = []
        if row_from <= row_to:
            cells = self.client.get_range_data(
                file_id,
                worksheet_id,
                row_from=row_from,
                row_to=row_to,
                col_from=0,
                col_to=len(definition.headers) - 1,
            )
        rows = self._rows(cells, definition.headers, row_from, row_to)
        return KDocsRowPageOut(
            target=target,
            target_name=definition.name,
            file_id=file_id,
            worksheet_id=worksheet_id,
            sheet_name=str(sheet.get("sheetName") or definition.name),
            file_url=self._safe_file_link(file_id),
            headers=list(definition.headers),
            total=total,
            page=page,
            page_size=page_size,
            items=rows,
        )

    def list_documents(self, query: str, page_size: int, page_token: str | None = None) -> KDocsDocumentPageOut:
        self._ensure_real_mcp()
        if not self.settings.kdocs_drive_id:
            raise ValueError("尚未配置金山 drive_id")
        payload = self.client.search_files(
            drive_id=self.settings.kdocs_drive_id,
            keyword=query,
            page_size=page_size,
            page_token=page_token,
        )
        items = self._find_value(payload, "items")
        documents = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            file_data = item.get("file")
            if not isinstance(file_data, dict):
                continue
            source = item.get("file_src") if isinstance(item.get("file_src"), dict) else {}
            modified_by = file_data.get("modified_by") if isinstance(file_data.get("modified_by"), dict) else {}
            documents.append(
                KDocsDocumentOut(
                    file_id=str(file_data.get("id") or ""),
                    name=str(file_data.get("name") or "未命名文件"),
                    path=str(source.get("path")) if source.get("path") else None,
                    size=int(file_data["size"]) if file_data.get("size") is not None else None,
                    modified_at=self._timestamp(file_data.get("mtime")),
                    modified_by=str(modified_by.get("name")) if modified_by.get("name") else None,
                    url=str(file_data.get("link_url")) if file_data.get("link_url") else None,
                )
            )
        next_page_token = self._find_value(payload, "next_page_token")
        return KDocsDocumentPageOut(
            query=query,
            page_size=page_size,
            next_page_token=str(next_page_token) if next_page_token else None,
            items=documents,
        )

    def _target_overview(self, definition: TargetDefinition) -> KDocsTargetOut:
        file_id = getattr(self.settings, definition.file_id_setting)
        worksheet_id = int(getattr(self.settings, definition.worksheet_id_setting))
        if not file_id or self.settings.kdocs_mode != "real" or self.settings.kdocs_transport != "mcp":
            return KDocsTargetOut(
                key=definition.key,
                name=definition.name,
                configured=bool(file_id),
                file_id=file_id,
                worksheet_id=worksheet_id,
            )
        try:
            sheet = self.client.get_sheet_info(file_id, worksheet_id)
            return KDocsTargetOut(
                key=definition.key,
                name=definition.name,
                configured=True,
                file_id=file_id,
                worksheet_id=worksheet_id,
                sheet_name=str(sheet.get("sheetName") or definition.name),
                total_rows=max(int(sheet.get("rowTo") or 0), 0),
            )
        except Exception:
            return KDocsTargetOut(
                key=definition.key,
                name=definition.name,
                configured=False,
                file_id=file_id,
                worksheet_id=worksheet_id,
            )

    def _ensure_real_mcp(self) -> None:
        if self.settings.kdocs_mode != "real" or self.settings.kdocs_transport != "mcp":
            raise ValueError("金山文档尚未启用 real/mcp 模式")
        missing = [
            name
            for name, value in {
                "KDOCS_ACCESS_TOKEN": self.settings.kdocs_access_token,
                "KDOCS_MCP_CLIENT_ID": self.settings.kdocs_mcp_client_id,
                "KDOCS_DRIVE_ID": self.settings.kdocs_drive_id,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"金山 MCP 配置缺失：{', '.join(missing)}")

    @classmethod
    def _rows(
        cls,
        cells: list[dict[str, Any]],
        headers: tuple[str, ...],
        row_from: int,
        row_to: int,
    ) -> list[KDocsRowOut]:
        values_by_row: dict[int, dict[str, Any]] = {}
        for cell in cells:
            row = int(cell.get("rowFrom", cell.get("originRow", -1)))
            col = int(cell.get("colFrom", cell.get("originCol", -1)))
            if row < row_from or row > row_to or col < 0 or col >= len(headers):
                continue
            value = cls._cell_value(cell)
            if value not in (None, ""):
                values_by_row.setdefault(row, {})[headers[col]] = value
        return [KDocsRowOut(row_index=row, values=values_by_row.get(row, {})) for row in range(row_from, row_to + 1)]

    @staticmethod
    def _cell_value(cell: dict[str, Any]) -> Any:
        for key in ("cellText", "originalCellValue", "value", "formula"):
            if cell.get(key) not in (None, ""):
                return cell[key]
        return None

    def _safe_file_link(self, file_id: str) -> str | None:
        try:
            return self.client.get_file_link(file_id)
        except Exception:
            return None

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        try:
            return datetime.fromtimestamp(int(value), tz=app_timezone()).isoformat()
        except (TypeError, ValueError, OSError):
            return None

    @classmethod
    def _find_value(cls, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for nested in value.values():
                found = cls._find_value(nested, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._find_value(nested, key)
                if found is not None:
                    return found
        return None
