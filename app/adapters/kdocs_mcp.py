import json
import threading
from typing import Any

import httpx


class KDocsMcpError(RuntimeError):
    pass


class KDocsMcpClient:
    """Small synchronous client for the WPS Skill Hub MCP endpoint."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._session_id: str | None = None
        self._request_id = 0
        self._session_lock = threading.RLock()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_session()
        rpc_payload = self._post_rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
            include_session=True,
        )
        return self._decode_tool_result(name, rpc_payload)

    def get_sheet_info(self, file_id: str, worksheet_id: int) -> dict[str, Any]:
        payload = self.call_tool("sheet.get_sheets_info", {"file_id": file_id})
        sheets = self._find_value(payload, "sheetsInfo")
        if not isinstance(sheets, list):
            raise KDocsMcpError("金山文档未返回工作表信息")
        for sheet in sheets:
            if isinstance(sheet, dict) and int(sheet.get("sheetId", -1)) == worksheet_id:
                return sheet
        raise KDocsMcpError(f"金山文档中不存在 worksheet_id={worksheet_id}")

    def get_range_data(
        self,
        file_id: str,
        worksheet_id: int,
        *,
        row_from: int,
        row_to: int,
        col_from: int,
        col_to: int,
    ) -> list[dict[str, Any]]:
        payload = self.call_tool(
            "sheet.get_range_data",
            {
                "file_id": file_id,
                "worksheet_id": worksheet_id,
                "range": {
                    "rowFrom": row_from,
                    "rowTo": row_to,
                    "colFrom": col_from,
                    "colTo": col_to,
                },
            },
        )
        cells = self._find_value(payload, "rangeData")
        return [cell for cell in cells if isinstance(cell, dict)] if isinstance(cells, list) else []

    def write_row(self, file_id: str, worksheet_id: int, row_index: int, values: list[Any]) -> dict[str, Any]:
        range_data = []
        for col_index, value in enumerate(values):
            if value is None or value == "":
                continue
            range_data.append(
                {
                    "opType": "formula",
                    "rowFrom": row_index,
                    "rowTo": row_index,
                    "colFrom": col_index,
                    "colTo": col_index,
                    "formula": self._cell_text(value),
                }
            )
        if not range_data:
            raise KDocsMcpError("金山文档写入行为空")
        return self.call_tool(
            "sheet.update_range_data",
            {
                "file_id": file_id,
                "worksheet_id": worksheet_id,
                "rangeData": range_data,
            },
        )

    def sort_range(
        self,
        file_id: str,
        worksheet_id: int,
        *,
        cell_range: str,
        key: str,
        key2: str | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "file_id": file_id,
            "worksheet_id": worksheet_id,
            "range": cell_range,
            "key": key,
            "order": "asc",
            "header": True,
        }
        if key2:
            arguments["key2"] = key2
            arguments["order2"] = "asc"
        return self.call_tool("sheet.range_sort", arguments)

    def upload_file(
        self,
        *,
        drive_id: str,
        parent_id: str,
        parent_path: list[str],
        name: str,
        content_base64: str,
        content_format: str | None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "drive_id": drive_id,
            "parent_id": parent_id,
            "parent_path": parent_path,
            "name": name,
            "content_base64": content_base64,
        }
        if content_format:
            arguments["content_format"] = content_format
        return self.call_tool("upload_file", arguments)

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        with self._session_lock:
            if self._session_id:
                return
            response = self._post(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_request_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {
                            "name": self.settings.app_name,
                            "version": "1.0.0",
                        },
                    },
                },
                include_session=False,
            )
            self._raise_for_rpc_error(response.json())
            self._session_id = response.headers.get("mcp-session-id")

    def _post_rpc(self, method: str, params: dict[str, Any], *, include_session: bool) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": method,
                "params": params,
            },
            include_session=include_session,
        )
        payload = response.json()
        self._raise_for_rpc_error(payload)
        return payload

    def _post(self, payload: dict[str, Any], *, include_session: bool) -> httpx.Response:
        headers = {
            "Authorization": self._authorization_header(),
            "X-Skill-Version": self.settings.kdocs_mcp_skill_version,
            "X-Client-Id": self.settings.kdocs_mcp_client_id,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if include_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = httpx.post(
            self.settings.kdocs_mcp_url,
            json=payload,
            headers=headers,
            timeout=self.settings.kdocs_timeout_seconds,
        )
        response.raise_for_status()
        return response

    def _authorization_header(self) -> str:
        token = (self.settings.kdocs_access_token or "").strip()
        return token if token.lower().startswith("bearer ") else f"Bearer {token}"

    def _next_request_id(self) -> int:
        with self._session_lock:
            self._request_id += 1
            return self._request_id

    @classmethod
    def _decode_tool_result(cls, name: str, rpc_payload: dict[str, Any]) -> dict[str, Any]:
        result = rpc_payload.get("result")
        if not isinstance(result, dict):
            raise KDocsMcpError(f"金山 MCP 工具 {name} 未返回结果")
        if result.get("isError"):
            raise KDocsMcpError(cls._content_message(result) or f"金山 MCP 工具 {name} 执行失败")

        for block in result.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = str(block.get("text") or "")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            cls._raise_for_business_error(name, payload)
            return payload
        return result

    @staticmethod
    def _raise_for_rpc_error(payload: Any) -> None:
        if not isinstance(payload, dict):
            raise KDocsMcpError("金山 MCP 返回了无效 JSON-RPC 响应")
        error = payload.get("error")
        if isinstance(error, dict):
            raise KDocsMcpError(str(error.get("message") or error.get("code") or "金山 MCP 调用失败"))

    @classmethod
    def _raise_for_business_error(cls, name: str, payload: dict[str, Any]) -> None:
        candidates = [payload]
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.append(data)
        for candidate in candidates:
            code = candidate.get("code")
            if code not in (None, 0, "0"):
                message = candidate.get("message") or candidate.get("msg") or candidate.get("hint")
                raise KDocsMcpError(f"金山 MCP 工具 {name} 失败：{message or code}")

    @staticmethod
    def _content_message(result: dict[str, Any]) -> str | None:
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                return str(block["text"])
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

    @staticmethod
    def _cell_text(value: Any) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        text = str(value)
        if text[:1] in {"=", "+", "-", "@"}:
            return f"'{text}"
        return text
