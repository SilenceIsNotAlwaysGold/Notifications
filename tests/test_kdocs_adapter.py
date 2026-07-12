import json
from decimal import Decimal

import httpx

from app.adapters.kdocs import KDocsAdapter
from app.core.config import get_settings


def reset_kdocs_real(monkeypatch):
    monkeypatch.setenv("KDOCS_MODE", "real")
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
