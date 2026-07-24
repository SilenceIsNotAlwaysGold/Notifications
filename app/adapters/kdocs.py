import base64
import logging
import re
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx

from app.adapters.kdocs_mcp import KDocsMcpClient
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_MCP_WRITE_LOCK = threading.RLock()


class KDocsAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.mode = self.settings.kdocs_mode
        self.transport = self.settings.kdocs_transport
        self.mcp = KDocsMcpClient(self.settings) if self.transport == "mcp" else None

    def update_case_status(self, case_no: str, status: str, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": {
                self.settings.kdocs_case_no_column: case_no,
                self.settings.kdocs_status_column: status,
            },
            "case_id": case_id,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "update_case_status",
                payload,
                lambda: self._mcp_upsert_enforcement({"案号": case_no, "案件状态": status}),
                target="enforcement",
            )
        return self._execute("update_case_status", payload)

    def update_paid_amount(self, case_no: str, paid_amount: Decimal, case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": {
                self.settings.kdocs_case_no_column: case_no,
                self.settings.kdocs_paid_amount_column: str(paid_amount),
            },
            "case_id": case_id,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "update_paid_amount",
                payload,
                lambda: self._mcp_upsert_enforcement({"案号": case_no, "已还欠款": str(paid_amount)}),
                target="enforcement",
            )
        return self._execute("update_paid_amount", payload)

    def append_archive_row(self, data: dict[str, Any], case_id: int | None = None, tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": data,
            "case_id": case_id,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "append_archive_row",
                payload,
                lambda: {
                    "skipped": True,
                    "reason": "MCP 真实表仅接收已完成业务字段映射的专用同步",
                },
            )
        return self._execute("append_archive_row", payload)

    def sync_case_snapshot(self, case_data: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        case_no = case_data.get("case_no")
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_case_sheet_id,
            "row_match": {self.settings.kdocs_case_no_column: case_no},
            "fields": case_data,
            "case_id": case_data.get("id"),
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "sync_case_snapshot",
                payload,
                lambda: self._mcp_upsert_enforcement(case_data),
                target="enforcement",
            )
        return self._execute("sync_case_snapshot", payload)

    def upload_legal_document(
        self,
        local_path: str,
        target_filename: str,
        metadata: dict[str, Any],
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "folder_id": self.settings.kdocs_judgment_folder_id,
            "target_filename": target_filename,
            "local_path": local_path,
            "metadata": metadata,
            "conflict_strategy": "rename",
        }
        if self.mode == "mock":
            file_id = f"mock-kdocs-file-{Path(target_filename).stem}"
            return self._mock_result(
                "upload_legal_document",
                payload,
                response={
                    "file_id": file_id,
                    "final_filename": target_filename,
                    "url": f"kdocs://{self.settings.kdocs_judgment_folder_id}/{target_filename}",
                },
            )
        if self.transport == "mcp":
            return self._mcp_execute(
                "upload_legal_document",
                payload,
                lambda: self._mcp_upload_legal_document(local_path, target_filename, metadata),
            )
        missing = self._missing_gateway_config()
        if missing:
            return self._missing_result("upload_legal_document", payload, missing)
        try:
            with open(local_path, "rb") as file_obj:
                response = httpx.post(
                    self._endpoint("files/upload"),
                    data={
                        "space_id": self.settings.kdocs_space_id,
                        "folder_id": self.settings.kdocs_judgment_folder_id,
                        "target_filename": target_filename,
                        "metadata": self._stringify(metadata),
                        "conflict_strategy": "rename",
                    },
                    files={"file": (target_filename, file_obj)},
                    headers=self._headers(),
                    timeout=self.settings.kdocs_timeout_seconds,
                )
            return self._response_result("upload_legal_document", payload, response)
        except Exception as exc:
            logger.exception("金山文档文件上传失败")
            return self._exception_result("upload_legal_document", payload, exc)

    def append_court_time_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_court_time_sheet_id,
            "sort_by": "开庭时间",
            "row": row,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "append_court_time_row",
                payload,
                lambda: self._mcp_append_court_time(row),
                target="court",
            )
        return self._execute("append_court_time_row", payload)

    def append_enforcement_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_enforcement_sheet_id,
            "row": row,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "append_enforcement_row",
                payload,
                lambda: self._mcp_upsert_enforcement(row),
                target="enforcement",
            )
        return self._execute("append_enforcement_row", payload)

    def append_payment_registration_row(self, row: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        payload = {
            "tenant_id": tenant_id,
            "space_id": self.settings.kdocs_space_id,
            "sheet_id": self.settings.kdocs_payment_sheet_id,
            "row": row,
        }
        if self._use_real_mcp():
            return self._mcp_execute(
                "append_payment_registration_row",
                payload,
                lambda: self._mcp_upsert_payment(row),
                target="payment",
            )
        return self._execute("append_payment_registration_row", payload)

    def read_row(self, *, target: str, file_id: str, worksheet_id: int, row_index: int) -> dict[str, Any]:
        if not self._use_real_mcp() or self.mcp is None:
            raise ValueError("金山 MCP 真实读取未启用")
        return self._mcp_readback(file_id, worksheet_id, row_index, target)

    def expected_row_values(self, target: str, payload: dict[str, Any]) -> list[Any]:
        """Build the mapped row used by the writer for reconciliation."""
        row = payload.get("row") or payload.get("fields") or payload
        if target == "enforcement":
            return self._enforcement_values(row)
        if target == "court":
            return self._court_time_values(row)
        if target == "payment":
            return self._payment_values(row)
        raise ValueError(f"不支持的金山对账目标：{target}")

    def _mcp_upsert_enforcement(self, row: dict[str, Any]) -> dict[str, Any]:
        assert self.mcp is not None
        file_id = self.settings.kdocs_enforcement_file_id or ""
        worksheet_id = self.settings.kdocs_enforcement_worksheet_id
        values = self._enforcement_values(row)
        case_no = self._pick(row, "民初案号", "案号", "case_no")
        with _MCP_WRITE_LOCK:
            sheet = self.mcp.get_sheet_info(file_id, worksheet_id)
            last_row = int(sheet.get("rowTo", 0))
            target_row = self._mcp_find_enforcement_row(file_id, worksheet_id, str(case_no), last_row) if case_no else None
            created = target_row is None
            if target_row is None:
                target_row = last_row + 1
            write_result = self.mcp.write_row(file_id, worksheet_id, target_row, values)
        return {
            "file_id": file_id,
            "worksheet_id": worksheet_id,
            "row_index": target_row,
            "created": created,
            "write": write_result,
        }

    def _mcp_find_enforcement_row(self, file_id: str, worksheet_id: int, case_no: str, last_row: int) -> int | None:
        assert self.mcp is not None
        if last_row < 1:
            return None
        cells = self.mcp.get_range_data(
            file_id,
            worksheet_id,
            row_from=1,
            row_to=last_row,
            col_from=18,
            col_to=18,
        )
        expected = case_no.strip()
        for cell in cells:
            value = cell.get("cellText") or cell.get("originalCellValue") or cell.get("formula")
            if str(value or "").strip() == expected:
                return int(cell.get("rowFrom", cell.get("originRow", -1)))
        return None

    def _mcp_append_court_time(self, row: dict[str, Any]) -> dict[str, Any]:
        assert self.mcp is not None
        file_id = self.settings.kdocs_court_time_file_id or ""
        worksheet_id = self.settings.kdocs_court_time_worksheet_id
        with _MCP_WRITE_LOCK:
            sheet = self.mcp.get_sheet_info(file_id, worksheet_id)
            target_row = int(sheet.get("rowTo", 0)) + 1
            write_result = self.mcp.write_row(file_id, worksheet_id, target_row, self._court_time_values(row))
            sort_result = self.mcp.sort_range(
                file_id,
                worksheet_id,
                cell_range=f"A1:R{target_row + 1}",
                key="B",
                key2="C",
            )
        return {
            "file_id": file_id,
            "worksheet_id": worksheet_id,
            "row_index": target_row,
            "write": write_result,
            "sort": sort_result,
        }

    def _mcp_upsert_payment(self, row: dict[str, Any]) -> dict[str, Any]:
        assert self.mcp is not None
        file_id = self.settings.kdocs_payment_file_id or ""
        worksheet_id = self.settings.kdocs_payment_worksheet_id
        case_no = self._pick(row, "案号", "case_no")
        with _MCP_WRITE_LOCK:
            sheet = self.mcp.get_sheet_info(file_id, worksheet_id)
            last_row = int(sheet.get("rowTo", 0))
            target_row = self._mcp_find_row(file_id, worksheet_id, str(case_no), last_row, 3) if case_no else None
            created = target_row is None
            if target_row is None:
                target_row = last_row + 1
                values = self._payment_values(row)
            else:
                existing = self._mcp_row_values(file_id, worksheet_id, target_row, 8)
                incoming = self._payment_values(row)
                values = [new if new not in (None, "") else old for old, new in zip(existing, incoming)]
            write_result = self.mcp.write_row(file_id, worksheet_id, target_row, values)
        return {
            "file_id": file_id,
            "worksheet_id": worksheet_id,
            "row_index": target_row,
            "created": created,
            "write": write_result,
        }

    def _mcp_find_row(
        self,
        file_id: str,
        worksheet_id: int,
        expected: str,
        last_row: int,
        column: int,
    ) -> int | None:
        assert self.mcp is not None
        if last_row < 1:
            return None
        cells = self.mcp.get_range_data(
            file_id, worksheet_id, row_from=1, row_to=last_row, col_from=column, col_to=column
        )
        normalized = expected.strip()
        for cell in cells:
            value = cell.get("cellText") or cell.get("originalCellValue") or cell.get("formula")
            if str(value or "").strip() == normalized:
                return int(cell.get("rowFrom", cell.get("originRow", -1)))
        return None

    def _mcp_row_values(self, file_id: str, worksheet_id: int, row_index: int, col_to: int) -> list[Any]:
        assert self.mcp is not None
        values: list[Any] = [None] * (col_to + 1)
        cells = self.mcp.get_range_data(
            file_id, worksheet_id, row_from=row_index, row_to=row_index, col_from=0, col_to=col_to
        )
        for cell in cells:
            column = int(cell.get("colFrom", cell.get("originCol", -1)))
            if 0 <= column <= col_to:
                values[column] = cell.get("cellText") or cell.get("originalCellValue") or cell.get("formula")
        return values

    def _mcp_upload_legal_document(
        self,
        local_path: str,
        target_filename: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        assert self.mcp is not None
        content = base64.b64encode(Path(local_path).read_bytes()).decode("ascii")
        final_filename = self._mcp_resolve_upload_filename(target_filename, metadata)
        suffix = Path(final_filename).suffix.lower().lstrip(".") or None
        upload_result = self.mcp.upload_file(
            drive_id=self.settings.kdocs_drive_id or "",
            parent_id=self.settings.kdocs_judgment_parent_id,
            parent_path=self._parent_path_parts(),
            name=final_filename,
            content_base64=content,
            content_format=suffix,
        )
        file_id = self._deep_find(upload_result, "file_id") or self._deep_find(upload_result, "fileId") or self._deep_find(upload_result, "id")
        final_filename = self._deep_find(upload_result, "name") or final_filename
        url = self._deep_find(upload_result, "url") or self._deep_find(upload_result, "link_url") or self._deep_find(upload_result, "link")
        if file_id and not url:
            link_result = self.mcp.call_tool("get_file_link", {"file_id": str(file_id)})
            url = self._deep_find(link_result, "url") or self._deep_find(link_result, "link_url") or self._deep_find(link_result, "link")
        return {
            "file_id": file_id,
            "final_filename": final_filename,
            "url": url,
            "drive_id": self.settings.kdocs_drive_id,
            "upload": upload_result,
        }

    def _mcp_resolve_upload_filename(self, target_filename: str, metadata: dict[str, Any]) -> str:
        if not self._mcp_filename_exists(target_filename):
            return target_filename
        path = Path(target_filename)
        suffix_parts = [metadata.get("case_no"), metadata.get("msg_id")]
        suffix = "-".join(self._safe_filename_part(value) for value in suffix_parts if value)
        candidate_stem = f"{path.stem}-{suffix or '副本'}"
        candidate = f"{candidate_stem}{path.suffix}"
        if not self._mcp_filename_exists(candidate):
            return candidate
        counter = 2
        while counter <= 99:
            candidate = f"{candidate_stem}-{counter}{path.suffix}"
            if not self._mcp_filename_exists(candidate):
                return candidate
            counter += 1
        raise ValueError("金山文档同名文件过多，无法生成唯一文件名")

    def _mcp_filename_exists(self, filename: str) -> bool:
        assert self.mcp is not None
        result = self.mcp.call_tool(
            "search_files",
            {
                "keyword": filename,
                "type": "file_name",
                "file_type": "file",
                "drive_ids": [self.settings.kdocs_drive_id],
                "page_size": 100,
            },
        )
        items = self._deep_find(result, "items")
        if not isinstance(items, list):
            return False
        return any(
            isinstance(item, dict) and str(item.get("name") or item.get("fname") or "") == filename
            for item in items
        )

    def _mcp_execute(
        self,
        operation: str,
        payload: dict[str, Any],
        callback: Callable[[], dict[str, Any]],
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        missing = self._missing_mcp_config(target)
        if missing:
            return self._missing_result(operation, payload, missing)
        try:
            response = callback()
            if target and isinstance(response, dict) and response.get("file_id") and response.get("row_index") is not None:
                response["readback"] = self._mcp_readback(
                    str(response["file_id"]),
                    int(response.get("worksheet_id", 0)),
                    int(response["row_index"]),
                    target,
                )
            return {
                "success": True,
                "mode": "real",
                "transport": "mcp",
                "sync_target": "kdocs",
                "operation": operation,
                "request_payload": payload,
                "response": response,
                "error": None,
            }
        except Exception as exc:
            logger.exception("金山 MCP 同步失败 operation=%s", operation)
            return self._exception_result(operation, payload, exc)

    def _mcp_readback(self, file_id: str, worksheet_id: int, row_index: int, target: str) -> dict[str, Any]:
        assert self.mcp is not None
        col_to = {"enforcement": 24, "court": 17, "payment": 8}.get(target, 24)
        cells = self.mcp.get_range_data(
            file_id,
            worksheet_id,
            row_from=row_index,
            row_to=row_index,
            col_from=0,
            col_to=col_to,
        )
        values: dict[str, Any] = {}
        for cell in cells:
            column = int(cell.get("colFrom", cell.get("originCol", -1)))
            value = cell.get("cellText") or cell.get("originalCellValue") or cell.get("formula")
            values[str(column)] = value
        return {"verified": bool(values), "row_index": row_index, "values": values}

    def _execute(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "mock":
            return self._mock_result(operation, payload)
        missing = self._missing_gateway_config()
        if missing:
            return self._missing_result(operation, payload, missing)
        try:
            response = httpx.post(
                self._endpoint(operation),
                json=payload,
                headers=self._headers(),
                timeout=self.settings.kdocs_timeout_seconds,
            )
            return self._response_result(operation, payload, response)
        except Exception as exc:
            logger.exception("金山文档同步失败 operation=%s", operation)
            return self._exception_result(operation, payload, exc)

    def _missing_gateway_config(self) -> list[str]:
        return [
            name
            for name, value in {
                "KDOCS_BASE_URL": self.settings.kdocs_base_url,
                "KDOCS_ACCESS_TOKEN": self.settings.kdocs_access_token,
                "KDOCS_SPACE_ID": self.settings.kdocs_space_id,
            }.items()
            if not value
        ]

    def _missing_mcp_config(self, target: str | None = None) -> list[str]:
        required = {
            "KDOCS_MCP_URL": self.settings.kdocs_mcp_url,
            "KDOCS_MCP_CLIENT_ID": self.settings.kdocs_mcp_client_id,
            "KDOCS_ACCESS_TOKEN": self.settings.kdocs_access_token,
            "KDOCS_DRIVE_ID": self.settings.kdocs_drive_id,
        }
        if target == "enforcement":
            required["KDOCS_ENFORCEMENT_FILE_ID"] = self.settings.kdocs_enforcement_file_id
        elif target == "court":
            required["KDOCS_COURT_TIME_FILE_ID"] = self.settings.kdocs_court_time_file_id
        elif target == "payment":
            required["KDOCS_PAYMENT_FILE_ID"] = self.settings.kdocs_payment_file_id
        return [name for name, value in required.items() if not value]

    def _use_real_mcp(self) -> bool:
        return self.mode == "real" and self.transport == "mcp"

    def _endpoint(self, operation: str) -> str:
        return f"{self.settings.kdocs_base_url.rstrip('/')}/kdocs/{operation}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.kdocs_access_token}"}

    def _parent_path_parts(self) -> list[str]:
        return [part.strip() for part in self.settings.kdocs_judgment_parent_path.split("/") if part.strip()]

    def _enforcement_values(self, row: dict[str, Any]) -> list[Any]:
        notes = self._pick(row, "备注")
        if not notes:
            note_parts = [
                self._pick(row, "文件名"),
                self._pick(row, "识别摘要", "extracted_text"),
                "需人工复核" if self._pick(row, "需人工复核") else None,
                f"消息ID:{self._pick(row, '消息ID', 'msg_id')}" if self._pick(row, "消息ID", "msg_id") else None,
            ]
            notes = "；".join(str(value) for value in note_parts if value)
        values = [None] * 25
        assignments = {
            0: self._pick(row, "代理人"),
            1: self._pick(row, "（法院组）代提交人", "代提交人"),
            2: self._pick(row, "原告主体", "原告", "plaintiff"),
            3: self._pick(row, "被告", "debtor_name", "defendant"),
            4: self._pick(row, "身份证"),
            5: self._pick(row, "文书执行类型", "文书类型", "document_type"),
            6: self._pick(row, "上传文件", "文件链接", "file_url"),
            7: self._pick(row, "文书签发时间"),
            8: self._pick(row, "应还款时间", "到期日", "due_date"),
            9: self._pick(row, "履约情况"),
            10: self._pick(row, "提交情况"),
            11: self._pick(row, "申请强制时间"),
            12: self._pick(row, "所提交的法院", "法院"),
            13: self._pick(row, "法院审核状态"),
            14: self._pick(row, "审核意见"),
            15: self._pick(row, "材料是否寄出"),
            16: self._pick(row, "物流单号"),
            17: self._pick(row, "执行案号"),
            18: self._pick(row, "民初案号", "案号", "case_no"),
            19: self._pick(row, "总金额", "total_amount"),
            20: self._pick(row, "已还欠款", "已还金额", "paid_amount"),
            21: self._pick(row, "法官电话"),
            22: self._pick(row, "案件状态", "状态", "status"),
            23: notes,
            24: self._pick(row, "订单号", "order_no"),
        }
        for index, value in assignments.items():
            values[index] = value
        return values

    def _court_time_values(self, row: dict[str, Any]) -> list[Any]:
        court_time = self._pick(row, "开庭时间", "court_time")
        court_date = court_time
        time_only = None
        if court_time:
            text = str(court_time)
            try:
                parsed = datetime.fromisoformat(text)
                court_date = parsed.date().isoformat()
                time_only = parsed.strftime("%H:%M")
            except ValueError:
                if "T" in text:
                    court_date = text.split("T", 1)[0]
                    time_only = text.split("T", 1)[1].split("+", 1)[0][:5]
        note_parts = [self._pick(row, "备注", "识别摘要")]
        message_id = self._pick(row, "消息ID", "msg_id")
        if message_id:
            note_parts.append(f"消息ID:{message_id}")
        values = [None] * 18
        assignments = {
            0: self._pick(row, "法院"),
            1: court_date,
            2: self._pick(row, "时间") or time_only,
            3: self._pick(row, "公司（原告）", "原告", "plaintiff"),
            4: self._pick(row, "民初案号", "案号", "case_no"),
            5: self._pick(row, "被告", "defendant", "debtor_name"),
            6: self._pick(row, "开庭方式"),
            7: self._pick(row, "跟进人"),
            8: self._pick(row, "交付时间_1"),
            9: self._pick(row, "回收时间"),
            10: self._pick(row, "代开庭邮寄单号"),
            11: self._pick(row, "金额", "amount"),
            12: self._pick(row, "代办事务") or "开庭传票",
            13: self._pick(row, "代理人"),
            14: "；".join(str(value) for value in note_parts if value),
            15: self._pick(row, "承办法官电话", "法官电话"),
            16: self._pick(row, "传票", "文件链接", "file_url"),
            17: self._pick(row, "核对") or ("待人工复核" if self._pick(row, "需人工复核") else "已识别"),
        }
        for index, value in assignments.items():
            values[index] = value
        return values

    def _payment_values(self, row: dict[str, Any]) -> list[Any]:
        event_type = self._pick(row, "事件类型", "event_type")
        is_paid = event_type == "payment_screenshot" or self._pick(row, "支付情况") in {"已支付", "paid"}
        return [
            self._pick(row, "日期", "notice_date", "payment_date"),
            self._pick(row, "原告", "plaintiff"),
            self._pick(row, "被告", "defendant", "debtor_name"),
            self._pick(row, "案号", "case_no"),
            self._pick(row, "缴费信息", "金额", "amount"),
            self._pick(row, "支付情况") or ("已支付" if is_paid else "待支付"),
            self._pick(row, "跟踪情况") or ("已识别付款凭证" if is_paid else "待首次催促"),
            self._pick(row, "剩余缴费时间") or ("已缴费" if is_paid else "+7天"),
            self._pick(row, "缴费截图上传", "文件链接", "file_url"),
        ]

    @staticmethod
    def _pick(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = row.get(key)
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _safe_filename_part(value: Any) -> str:
        return re.sub(r"[\\/:*?\"<>|\r\n]+", "_", str(value)).strip(" ._") or "未知"

    @classmethod
    def _deep_find(cls, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            if key in value and value[key] not in (None, ""):
                return value[key]
            for nested in value.values():
                found = cls._deep_find(nested, key)
                if found not in (None, ""):
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = cls._deep_find(nested, key)
                if found not in (None, ""):
                    return found
        return None

    def _mock_result(self, operation: str, payload: dict[str, Any], response: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "success": True,
            "mode": "mock",
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": response or {"mock": True, "operation": operation},
            "error": None,
        }

    def _missing_result(self, operation: str, payload: dict[str, Any], missing: list[str]) -> dict[str, Any]:
        return {
            "success": False,
            "mode": self.mode,
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": None,
            "error": f"金山文档真实同步配置缺失：{', '.join(missing)}",
        }

    def _exception_result(self, operation: str, payload: dict[str, Any], exc: Exception) -> dict[str, Any]:
        return {
            "success": False,
            "mode": self.mode,
            "transport": self.transport,
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": None,
            "error": str(exc),
        }

    def _response_result(self, operation: str, payload: dict[str, Any], response: httpx.Response) -> dict[str, Any]:
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"text": response.text}
        business_success = response_payload.get("success") is not False if isinstance(response_payload, dict) else True
        success = response.status_code < 400 and business_success
        return {
            "success": success,
            "mode": "real",
            "transport": "gateway",
            "sync_target": "kdocs",
            "operation": operation,
            "request_payload": payload,
            "response": response_payload,
            "error": None if success else self._response_error(response, response_payload),
        }

    @staticmethod
    def _response_error(response: httpx.Response, response_payload: Any) -> str:
        if response.status_code >= 400:
            return f"金山文档 API HTTP {response.status_code}"
        if isinstance(response_payload, dict):
            return str(response_payload.get("error") or response_payload.get("message") or "金山文档网关返回业务失败")
        return "金山文档网关返回业务失败"

    @staticmethod
    def _stringify(value: dict[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
