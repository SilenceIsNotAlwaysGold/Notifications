import json
import base64
from decimal import Decimal

import httpx

from app.adapters.kdocs import KDocsAdapter
from app.core.config import get_settings


def reset_kdocs_real(monkeypatch):
    monkeypatch.setenv("KDOCS_MODE", "real")
    monkeypatch.setenv("KDOCS_TRANSPORT", "gateway")
    monkeypatch.setenv("KDOCS_BASE_URL", "https://kdocs-gateway.test")
    monkeypatch.setenv("KDOCS_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("KDOCS_SPACE_ID", "space_001")
    get_settings.cache_clear()


def test_real_gateway_upload_uses_multipart_contract(tmp_path, monkeypatch):
    reset_kdocs_real(monkeypatch)
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        captured["headers"] = kwargs.get("headers")
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"file_id": "file_001", "url": "https://kdocs.test/file_001"}, request=request)

    monkeypatch.setattr("app.adapters.kdocs.httpx.post", fake_post)
    local_file = tmp_path / "判决书.pdf"
    local_file.write_bytes(b"pdf bytes")

    result = KDocsAdapter().upload_legal_document(
        str(local_file),
        "李四-张三{判决书}.pdf",
        {"case_no": "(2026)黔0281民初3118号", "requires_review": False},
    )

    assert result["success"] is True
    assert captured["url"] == "https://kdocs-gateway.test/kdocs/files/upload"
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert captured["data"]["space_id"] == "space_001"
    assert captured["data"]["folder_id"] == "致和法务/判决书文件"
    assert captured["data"]["target_filename"] == "李四-张三{判决书}.pdf"
    assert captured["data"]["conflict_strategy"] == "rename"
    assert result["request_payload"]["conflict_strategy"] == "rename"
    assert json.loads(captured["data"]["metadata"])["requires_review"] is False
    assert captured["files"]["file"][0] == "李四-张三{判决书}.pdf"


def test_real_gateway_table_operations_use_json_contract(monkeypatch):
    reset_kdocs_real(monkeypatch)
    captured = []

    def fake_post(url, **kwargs):
        captured.append({"url": url, "json": kwargs.get("json"), "headers": kwargs.get("headers")})
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"success": True, "row_id": f"row_{len(captured)}"}, request=request)

    monkeypatch.setattr("app.adapters.kdocs.httpx.post", fake_post)
    adapter = KDocsAdapter()

    adapter.update_case_status("(2026)黔0281民初3118号", "overdue", case_id=1)
    adapter.update_paid_amount("(2026)黔0281民初3118号", Decimal("400.00"), case_id=1)
    adapter.append_court_time_row({"案号": "(2026)黔0281民初3118号", "开庭时间": "2026-07-02T15:00:00+08:00"})
    adapter.append_enforcement_row({"案号": "(2026)黔0281民初3118号", "文书类型": "判决书"})
    adapter.append_payment_registration_row({"案号": "(2026)黔0281民初3118号", "缴费类型": "缴费通知"})

    assert [item["url"] for item in captured] == [
        "https://kdocs-gateway.test/kdocs/update_case_status",
        "https://kdocs-gateway.test/kdocs/update_paid_amount",
        "https://kdocs-gateway.test/kdocs/append_court_time_row",
        "https://kdocs-gateway.test/kdocs/append_enforcement_row",
        "https://kdocs-gateway.test/kdocs/append_payment_registration_row",
    ]
    assert all(item["headers"] == {"Authorization": "Bearer secret-token"} for item in captured)
    assert captured[0]["json"]["space_id"] == "space_001"
    assert captured[0]["json"]["row_match"] == {"案号": "(2026)黔0281民初3118号"}
    assert captured[1]["json"]["fields"]["已还金额"] == "400.00"
    assert captured[2]["json"]["sort_by"] == "开庭时间"
    assert captured[3]["json"]["sheet_id"] == "致和法务/强制执行进度表格"
    assert captured[4]["json"]["sheet_id"] == "致和法务/缴费登记"


def test_real_gateway_business_failure_is_failed_even_with_http_200(monkeypatch):
    reset_kdocs_real(monkeypatch)

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"success": False, "error": "invalid sheet mapping"}, request=request)

    monkeypatch.setattr("app.adapters.kdocs.httpx.post", fake_post)

    result = KDocsAdapter().append_court_time_row({"案号": "(2026)黔0281民初3118号"})

    assert result["success"] is False
    assert result["error"] == "invalid sheet mapping"
    assert result["response"] == {"success": False, "error": "invalid sheet mapping"}


def reset_kdocs_mcp(monkeypatch):
    monkeypatch.setenv("KDOCS_MODE", "real")
    monkeypatch.setenv("KDOCS_TRANSPORT", "mcp")
    monkeypatch.setenv("KDOCS_ACCESS_TOKEN", "Bearer test-token")
    monkeypatch.setenv("KDOCS_MCP_URL", "https://mcp.kdocs.test")
    monkeypatch.setenv("KDOCS_MCP_CLIENT_ID", "client-001")
    monkeypatch.setenv("KDOCS_DRIVE_ID", "drive-001")
    monkeypatch.setenv("KDOCS_JUDGMENT_PARENT_ID", "0")
    monkeypatch.setenv("KDOCS_JUDGMENT_PARENT_PATH", "致和法务/判决书文件")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_FILE_ID", "enforcement-file")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_WORKSHEET_ID", "10")
    monkeypatch.setenv("KDOCS_COURT_TIME_FILE_ID", "court-file")
    monkeypatch.setenv("KDOCS_COURT_TIME_WORKSHEET_ID", "1")
    monkeypatch.setenv("KDOCS_PAYMENT_FILE_ID", "")
    get_settings.cache_clear()


def mcp_response(payload, *, session=False):
    request = httpx.Request("POST", "https://mcp.kdocs.test")
    headers = {"mcp-session-id": "session-001"} if session else None
    return httpx.Response(200, json=payload, headers=headers, request=request)


def mcp_tool_response(payload):
    return mcp_response(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]},
        }
    )


def test_real_mcp_maps_enforcement_and_court_rows_by_fixed_column(monkeypatch):
    reset_kdocs_mcp(monkeypatch)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs)
        rpc = kwargs["json"]
        if rpc["method"] == "initialize":
            return mcp_response(
                {"jsonrpc": "2.0", "id": rpc["id"], "result": {"protocolVersion": "2025-03-26"}},
                session=True,
            )
        name = rpc["params"]["name"]
        arguments = rpc["params"]["arguments"]
        if name == "sheet.get_sheets_info":
            row_to = 1188 if arguments["file_id"] == "enforcement-file" else 442
            worksheet_id = 10 if arguments["file_id"] == "enforcement-file" else 1
            return mcp_tool_response(
                {"code": 0, "data": {"detail": {"sheetsInfo": [{"sheetId": worksheet_id, "rowTo": row_to}]}}}
            )
        if name == "sheet.get_range_data":
            return mcp_tool_response({"code": 0, "data": {"detail": {"rangeData": []}}})
        return mcp_tool_response({"code": 0, "data": {"detail": {"result": "ok"}}})

    monkeypatch.setattr("app.adapters.kdocs_mcp.httpx.post", fake_post)
    adapter = KDocsAdapter()

    enforcement = adapter.append_enforcement_row(
        {
            "案号": "(2026)黔0281民初3118号",
            "原告": "甲公司",
            "被告": "张三",
            "文书类型": "判决书",
            "文件链接": "https://kdocs.test/judgment.pdf",
            "总金额": "12000.00",
        }
    )
    court = adapter.append_court_time_row(
        {
            "案号": "(2026)黔0281民初3118号",
            "原告": "甲公司",
            "被告": "张三",
            "开庭时间": "2026-07-22T09:30:00+08:00",
            "文件链接": "https://kdocs.test/summons.pdf",
        }
    )

    tool_calls = [item["json"]["params"] for item in calls if item["json"]["method"] == "tools/call"]
    writes = [item for item in tool_calls if item["name"] == "sheet.update_range_data"]
    enforcement_cells = {item["colFrom"]: item["formula"] for item in writes[0]["arguments"]["rangeData"]}
    court_cells = {item["colFrom"]: item["formula"] for item in writes[1]["arguments"]["rangeData"]}

    assert enforcement["success"] is True
    assert enforcement["response"]["row_index"] == 1189
    assert enforcement_cells[2] == "甲公司"
    assert enforcement_cells[3] == "张三"
    assert enforcement_cells[5] == "判决书"
    assert enforcement_cells[6] == "https://kdocs.test/judgment.pdf"
    assert enforcement_cells[18] == "(2026)黔0281民初3118号"
    assert enforcement_cells[19] == "12000.00"

    assert court["success"] is True
    assert court["response"]["row_index"] == 443
    assert court_cells[1] == "2026-07-22"
    assert court_cells[2] == "09:30"
    assert court_cells[3] == "甲公司"
    assert court_cells[4] == "(2026)黔0281民初3118号"
    assert court_cells[5] == "张三"
    assert court_cells[16] == "https://kdocs.test/summons.pdf"
    sort_call = next(item for item in tool_calls if item["name"] == "sheet.range_sort")
    assert sort_call["arguments"]["range"] == "A1:R444"
    assert sort_call["arguments"]["key"] == "B"
    assert sort_call["arguments"]["key2"] == "C"

    assert all(item["headers"]["Authorization"] == "Bearer test-token" for item in calls)
    assert all(item["headers"]["X-Client-Id"] == "client-001" for item in calls)


def test_real_mcp_updates_existing_enforcement_case_row(monkeypatch):
    reset_kdocs_mcp(monkeypatch)
    writes = []

    def fake_post(url, **kwargs):
        rpc = kwargs["json"]
        if rpc["method"] == "initialize":
            return mcp_response(
                {"jsonrpc": "2.0", "id": rpc["id"], "result": {"protocolVersion": "2025-03-26"}},
                session=True,
            )
        name = rpc["params"]["name"]
        if name == "sheet.get_sheets_info":
            return mcp_tool_response({"code": 0, "data": {"detail": {"sheetsInfo": [{"sheetId": 10, "rowTo": 20}]}}})
        if name == "sheet.get_range_data":
            return mcp_tool_response(
                {
                    "code": 0,
                    "data": {
                        "detail": {
                            "rangeData": [
                                {"rowFrom": 7, "colFrom": 18, "cellText": "(2026)黔0281民初3118号"}
                            ]
                        }
                    },
                }
            )
        writes.append(rpc["params"])
        return mcp_tool_response({"code": 0, "data": {"detail": {"result": "ok"}}})

    monkeypatch.setattr("app.adapters.kdocs_mcp.httpx.post", fake_post)

    result = KDocsAdapter().update_paid_amount("(2026)黔0281民初3118号", Decimal("400.00"))

    assert result["success"] is True
    assert result["response"]["created"] is False
    assert result["response"]["row_index"] == 7
    cells = writes[0]["arguments"]["rangeData"]
    assert {(item["rowFrom"], item["colFrom"], item["formula"]) for item in cells} == {
        (7, 18, "(2026)黔0281民初3118号"),
        (7, 20, "400.00"),
    }


def test_real_mcp_upload_uses_parent_path_without_logging_content(tmp_path, monkeypatch):
    reset_kdocs_mcp(monkeypatch)
    calls = []

    def fake_post(url, **kwargs):
        rpc = kwargs["json"]
        if rpc["method"] == "initialize":
            return mcp_response(
                {"jsonrpc": "2.0", "id": rpc["id"], "result": {"protocolVersion": "2025-03-26"}},
                session=True,
            )
        calls.append(rpc["params"])
        if rpc["params"]["name"] == "search_files":
            return mcp_tool_response({"code": 0, "data": {"data": {"items": []}}})
        if rpc["params"]["name"] == "upload_file":
            return mcp_tool_response(
                {"code": 0, "data": {"detail": {"file_id": "file-001", "name": "甲公司-张三{判决书}.pdf"}}}
            )
        return mcp_tool_response({"code": 0, "data": {"link_url": "https://kdocs.test/file-001"}})

    monkeypatch.setattr("app.adapters.kdocs_mcp.httpx.post", fake_post)
    local_file = tmp_path / "judgment.pdf"
    local_file.write_bytes(b"pdf bytes")

    result = KDocsAdapter().upload_legal_document(
        str(local_file),
        "甲公司-张三{判决书}.pdf",
        {"case_no": "(2026)黔0281民初3118号"},
    )

    upload_args = next(item["arguments"] for item in calls if item["name"] == "upload_file")
    assert result["success"] is True
    assert result["response"]["file_id"] == "file-001"
    assert result["response"]["url"] == "https://kdocs.test/file-001"
    assert upload_args["drive_id"] == "drive-001"
    assert upload_args["parent_id"] == "0"
    assert upload_args["parent_path"] == ["致和法务", "判决书文件"]
    assert upload_args["content_base64"] == base64.b64encode(b"pdf bytes").decode("ascii")
    assert "content_base64" not in json.dumps(result["request_payload"], ensure_ascii=False)


def test_real_mcp_upload_renames_when_external_file_already_exists(tmp_path, monkeypatch):
    reset_kdocs_mcp(monkeypatch)
    uploaded_names = []
    searched_names = []

    def fake_post(url, **kwargs):
        rpc = kwargs["json"]
        if rpc["method"] == "initialize":
            return mcp_response(
                {"jsonrpc": "2.0", "id": rpc["id"], "result": {"protocolVersion": "2025-03-26"}},
                session=True,
            )
        name = rpc["params"]["name"]
        arguments = rpc["params"]["arguments"]
        if name == "search_files":
            searched_names.append(arguments["keyword"])
            items = [{"name": arguments["keyword"]}] if len(searched_names) == 1 else []
            return mcp_tool_response({"code": 0, "data": {"data": {"items": items}}})
        if name == "upload_file":
            uploaded_names.append(arguments["name"])
            return mcp_tool_response(
                {"code": 0, "data": {"detail": {"file_id": "file-002", "name": arguments["name"], "url": "https://kdocs.test/file-002"}}}
            )
        raise AssertionError(name)

    monkeypatch.setattr("app.adapters.kdocs_mcp.httpx.post", fake_post)
    local_file = tmp_path / "judgment.pdf"
    local_file.write_bytes(b"pdf bytes")

    result = KDocsAdapter().upload_legal_document(
        str(local_file),
        "甲公司-张三{判决书}.pdf",
        {"case_no": "(2026)黔0281民初3118号", "msg_id": "msg-001"},
    )

    assert result["success"] is True
    assert uploaded_names == ["甲公司-张三{判决书}-(2026)黔0281民初3118号-msg-001.pdf"]
    assert result["response"]["final_filename"] == uploaded_names[0]


def test_real_mcp_payment_target_is_required_only_for_payment(monkeypatch):
    reset_kdocs_mcp(monkeypatch)

    result = KDocsAdapter().append_payment_registration_row({"案号": "(2026)黔0281民初3118号"})

    assert result["success"] is False
    assert "KDOCS_PAYMENT_FILE_ID" in result["error"]
