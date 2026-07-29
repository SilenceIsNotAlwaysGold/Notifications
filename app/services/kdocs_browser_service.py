import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.adapters.kdocs_mcp import KDocsMcpClient
from app.core.config import Settings, get_settings
from app.schemas.kdocs_browser import (
    KDocsBrowserOverviewOut,
    KDocsDocumentOut,
    KDocsDocumentPageOut,
    KDocsRowOut,
    KDocsRowMutationOut,
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
        headers=("日期", "原告", "被告", "案号", "缴费信息", "支付情况", "跟踪情况", "剩余缴费时间", "缴费截图上传"),
    ),
    "repayment": TargetDefinition(
        key="repayment",
        name="还款与仲裁",
        file_id_setting="kdocs_enforcement_file_id",
        worksheet_id_setting="kdocs_repayment_worksheet_id",
        headers=(
            "甲方（债权人）", "乙方（债务人）", "协议文本", "证据情况", "提交 履约情况", "仲裁机构",
            "仲裁案号", "审核意见", "提交时间", "通过日期", "仲裁案件进度", "缴费情况", "还款方案",
            "还款情况", "合计还款",
        ),
    ),
}


class KDocsBrowserService:
    CACHE_TTL_SECONDS = 60.0
    _rows_cache: dict[tuple[str, int], tuple[float, int, list[KDocsRowOut]]] = {}
    _cache_lock = threading.RLock()

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

    def list_rows(
        self,
        target: KDocsTarget,
        page: int,
        page_size: int,
        *,
        query: str = "",
        filter_column: str = "",
        filter_value: str = "",
        sort_column: str = "",
        court_mode: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        sort_order: str = "asc",
        refresh: bool = False,
    ) -> KDocsRowPageOut:
        self._ensure_real_mcp()
        definition = TARGETS[target]
        file_id = str(getattr(self.settings, definition.file_id_setting) or "")
        worksheet_id = int(getattr(self.settings, definition.worksheet_id_setting))
        if not file_id:
            raise ValueError(f"{definition.name}尚未配置 file_id")
        sheet = self.client.get_sheet_info(file_id, worksheet_id)
        last_row = max(int(sheet.get("rowTo") or 0), 0)
        if filter_column and filter_column not in definition.headers:
            raise ValueError("筛选字段不存在")
        if filter_value and not filter_column:
            raise ValueError("请选择筛选字段")
        if sort_column and sort_column not in definition.headers:
            raise ValueError("排序字段不存在")
        needs_full_scan = bool(query or filter_value or sort_column or court_mode or date_from or date_to)
        if needs_full_scan:
            rows = self._all_rows(file_id, worksheet_id, definition.headers, last_row, refresh=refresh)
            rows = self._filter_rows(
                rows,
                target,
                query,
                filter_column,
                filter_value,
                court_mode,
                date_from,
                date_to,
            )
            rows = self._sort_rows(rows, sort_column, sort_order)
            total = len(rows)
            start = (page - 1) * page_size
            rows = rows[start:start + page_size]
        else:
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
            query=query,
            filter_column=filter_column,
            filter_value=filter_value,
            sort_column=sort_column,
            court_mode=court_mode,
            date_from=date_from,
            date_to=date_to,
            sort_order=sort_order,
            items=rows,
        )

    def update_row(
        self,
        target: KDocsTarget,
        row_index: int,
        values: dict[str, Any],
        row_version: str,
    ) -> KDocsRowMutationOut:
        definition, file_id, worksheet_id, last_row = self._mutation_target(target, row_index)
        unknown_columns = set(values) - set(definition.headers)
        if unknown_columns:
            raise ValueError(f"字段不存在：{', '.join(sorted(unknown_columns))}")
        current = self._read_row(file_id, worksheet_id, definition.headers, row_index)
        if current.row_version != row_version:
            raise ValueError("该行内容已发生变化，请刷新后重试")
        merged = {header: current.values.get(header, "") for header in definition.headers}
        merged.update(values)
        self.client.update_row(
            file_id,
            worksheet_id,
            row_index,
            [merged[header] for header in definition.headers],
        )
        updated = self._read_row(file_id, worksheet_id, definition.headers, row_index)
        mismatched = [
            header
            for header, value in values.items()
            if self._comparable_cell(updated.values.get(header)) != self._comparable_cell(value)
        ]
        if mismatched:
            self._invalidate_cache(file_id, worksheet_id)
            raise RuntimeError(f"金山文档写后校验失败：{', '.join(mismatched)}")
        self._invalidate_cache(file_id, worksheet_id)
        return KDocsRowMutationOut(
            target=target,
            target_name=definition.name,
            row_index=row_index,
            row_number=row_index + 1,
            values=updated.values,
            row_version=updated.row_version,
        )

    def delete_row(self, target: KDocsTarget, row_index: int, row_version: str) -> KDocsRowMutationOut:
        definition, file_id, worksheet_id, _ = self._mutation_target(target, row_index)
        current = self._read_row(file_id, worksheet_id, definition.headers, row_index)
        if current.row_version != row_version:
            raise ValueError("该行内容已发生变化，请刷新后重试")
        self.client.delete_row(file_id, worksheet_id, row_index, len(definition.headers) - 1)
        self._invalidate_cache(file_id, worksheet_id)
        return KDocsRowMutationOut(
            target=target,
            target_name=definition.name,
            row_index=row_index,
            row_number=row_index + 1,
            values=current.values,
        )

    def _mutation_target(
        self,
        target: KDocsTarget,
        row_index: int,
    ) -> tuple[TargetDefinition, str, int, int]:
        self._ensure_real_mcp()
        definition = TARGETS[target]
        file_id = str(getattr(self.settings, definition.file_id_setting) or "")
        worksheet_id = int(getattr(self.settings, definition.worksheet_id_setting))
        if not file_id:
            raise ValueError(f"{definition.name}尚未配置 file_id")
        sheet = self.client.get_sheet_info(file_id, worksheet_id)
        last_row = max(int(sheet.get("rowTo") or 0), 0)
        if row_index < 1 or row_index > last_row:
            raise ValueError("表格行不存在，请刷新后重试")
        return definition, file_id, worksheet_id, last_row

    def _read_row(
        self,
        file_id: str,
        worksheet_id: int,
        headers: tuple[str, ...],
        row_index: int,
    ) -> KDocsRowOut:
        cells = self.client.get_range_data(
            file_id,
            worksheet_id,
            row_from=row_index,
            row_to=row_index,
            col_from=0,
            col_to=len(headers) - 1,
        )
        return self._rows(cells, headers, row_index, row_index)[0]

    @classmethod
    def _invalidate_cache(cls, file_id: str, worksheet_id: int) -> None:
        with cls._cache_lock:
            cls._rows_cache.pop((file_id, worksheet_id), None)

    def _all_rows(
        self,
        file_id: str,
        worksheet_id: int,
        headers: tuple[str, ...],
        last_row: int,
        *,
        refresh: bool = False,
    ) -> list[KDocsRowOut]:
        cache_key = (file_id, worksheet_id)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._rows_cache.get(cache_key)
            if not refresh and cached and cached[0] > now and cached[1] == last_row:
                return cached[2]
        cells = []
        if last_row:
            cells = self.client.get_range_data(
                file_id,
                worksheet_id,
                row_from=1,
                row_to=last_row,
                col_from=0,
                col_to=len(headers) - 1,
            )
        rows = self._rows(cells, headers, 1, last_row)
        with self._cache_lock:
            self._rows_cache[cache_key] = (now + self.CACHE_TTL_SECONDS, last_row, rows)
        return rows

    @classmethod
    def _filter_rows(
        cls,
        rows: list[KDocsRowOut],
        target: KDocsTarget,
        query: str,
        filter_column: str,
        filter_value: str,
        court_mode: str,
        date_from: str | None,
        date_to: str | None,
    ) -> list[KDocsRowOut]:
        query_normalized = query.casefold()
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
        result = []
        for row in rows:
            values = row.values
            if query_normalized and not any(query_normalized in str(value).casefold() for value in values.values()):
                continue
            if filter_value and filter_value.casefold() not in str(values.get(filter_column) or "").casefold():
                continue
            if target == "court" and court_mode and court_mode not in str(values.get("开庭方式") or ""):
                continue
            if target == "court" and (start or end):
                hearing_date = cls._court_datetime(values.get("开庭时间"))
                if hearing_date is None or (start and hearing_date.date() < start) or (end and hearing_date.date() > end):
                    continue
            result.append(row)
        return result

    @classmethod
    def _sort_rows(cls, rows: list[KDocsRowOut], sort_column: str, sort_order: str) -> list[KDocsRowOut]:
        if not sort_column:
            return rows
        reverse = sort_order == "desc"
        populated = [row for row in rows if row.values.get(sort_column) not in (None, "")]
        empty = [row for row in rows if row.values.get(sort_column) in (None, "")]
        dated = [(cls._court_datetime(row.values.get(sort_column)), row) for row in populated]
        if any(value is not None for value, _ in dated):
            valid = [(value, row) for value, row in dated if value is not None]
            invalid = [row for value, row in dated if value is None]
            valid.sort(key=lambda item: (item[0], item[1].row_index), reverse=reverse)
            invalid.sort(key=lambda row: str(row.values.get(sort_column)).casefold(), reverse=reverse)
            return [row for _, row in valid] + invalid + empty
        numeric = []
        non_numeric = []
        for row in rows:
            value = row.values.get(sort_column)
            if value in (None, ""):
                continue
            try:
                normalized = str(value).replace(",", "").replace("¥", "").replace("￥", "").strip()
                numeric.append((Decimal(normalized), row))
            except (InvalidOperation, ValueError):
                non_numeric.append(row)
        if numeric and not non_numeric:
            numeric.sort(key=lambda item: (item[0], item[1].row_index), reverse=reverse)
            return [row for _, row in numeric] + empty
        populated.sort(key=lambda row: (str(row.values.get(sort_column)).casefold(), row.row_index), reverse=reverse)
        return populated + empty

    @staticmethod
    def _court_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        match = re.search(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})(?:日)?(?:\s+|T)?(\d{1,2})?(?::|时)?(\d{1,2})?", text)
        if not match:
            return None
        try:
            year, month, day, hour, minute = match.groups()
            return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=app_timezone())
        except ValueError:
            return None

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
        return [
            KDocsRowOut(
                row_index=row,
                values=values_by_row.get(row, {}),
                row_version=cls._row_version(row, values_by_row.get(row, {})),
            )
            for row in range(row_from, row_to + 1)
        ]

    @staticmethod
    def _row_version(row_index: int, values: dict[str, Any]) -> str:
        payload = json.dumps(
            {"row_index": row_index, "values": values},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _comparable_cell(value: Any) -> str:
        return "" if value is None else str(value)

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
