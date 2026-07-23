from app.core.config import get_settings
from app.core.permissions import has_permission
from app.services.kdocs_browser_service import KDocsBrowserService


class FakeKDocsClient:
    def __init__(self):
        self.range_calls = []

    def get_sheet_info(self, file_id, worksheet_id):
        rows = {"enforcement-file": 75, "court-file": 20, "payment-file": 3}
        names = {"enforcement-file": "法院组 强制执行代理", "court-file": "现在的开庭表格", "payment-file": "Sheet1"}
        return {"sheetId": worksheet_id, "sheetName": names[file_id], "rowTo": rows[file_id]}

    def get_range_data(self, file_id, worksheet_id, *, row_from, row_to, col_from, col_to):
        self.range_calls.append((file_id, worksheet_id, row_from, row_to, col_from, col_to))
        return [
            {"rowFrom": row_from, "colFrom": 2, "cellText": "甲公司"},
            {"rowFrom": row_from, "colFrom": 3, "cellText": "张三"},
            {"rowFrom": row_from, "colFrom": 18, "cellText": "（2026）粤0101民初123号"},
            {"rowFrom": row_from + 1, "colFrom": 19, "originalCellValue": 5000},
        ]

    def get_file_link(self, file_id):
        return f"https://www.kdocs.cn/l/{file_id}"

    def search_files(self, *, drive_id, keyword, page_size, page_token=None):
        assert drive_id == "drive-001"
        assert keyword == "判决书"
        assert page_size == 30
        assert page_token is None
        return {
            "code": 0,
            "data": {
                "items": [
                    {
                        "file": {
                            "id": "doc-001",
                            "name": "甲公司-张三判决书.pdf",
                            "size": 2048,
                            "mtime": 1781957638,
                            "link_url": "https://www.kdocs.cn/l/doc-001",
                            "modified_by": {"id": "private-user-id", "name": "法务A", "avatar": "private-avatar"},
                        },
                        "file_src": {"path": "致和法务/判决书"},
                    }
                ],
                "next_page_token": "next-001",
            },
        }


def kdocs_settings(monkeypatch):
    monkeypatch.setenv("KDOCS_MODE", "real")
    monkeypatch.setenv("KDOCS_TRANSPORT", "mcp")
    monkeypatch.setenv("KDOCS_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("KDOCS_MCP_CLIENT_ID", "client-001")
    monkeypatch.setenv("KDOCS_DRIVE_ID", "drive-001")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_FILE_ID", "enforcement-file")
    monkeypatch.setenv("KDOCS_ENFORCEMENT_WORKSHEET_ID", "10")
    monkeypatch.setenv("KDOCS_COURT_TIME_FILE_ID", "court-file")
    monkeypatch.setenv("KDOCS_COURT_TIME_WORKSHEET_ID", "1")
    monkeypatch.setenv("KDOCS_PAYMENT_FILE_ID", "payment-file")
    monkeypatch.setenv("KDOCS_PAYMENT_WORKSHEET_ID", "1")
    get_settings.cache_clear()
    return get_settings()


def test_kdocs_browser_overview_reads_live_sheet_counts(monkeypatch):
    service = KDocsBrowserService(kdocs_settings(monkeypatch), FakeKDocsClient())

    overview = service.overview()

    assert overview.configured is True
    assert overview.drive_id == "drive-001"
    assert [(item.key, item.total_rows) for item in overview.targets] == [
        ("enforcement", 75),
        ("court", 20),
        ("payment", 3),
    ]


def test_kdocs_browser_maps_sparse_cells_and_paginates(monkeypatch):
    client = FakeKDocsClient()
    service = KDocsBrowserService(kdocs_settings(monkeypatch), client)

    result = service.list_rows("enforcement", page=2, page_size=30)

    assert result.total == 75
    assert result.page == 2
    assert result.items[0].row_index == 31
    assert result.items[0].values["原告主体"] == "甲公司"
    assert result.items[0].values["被告"] == "张三"
    assert result.items[0].values["民初案号"] == "（2026）粤0101民初123号"
    assert result.items[1].values["总金额"] == 5000
    assert result.file_url == "https://www.kdocs.cn/l/enforcement-file"
    assert client.range_calls == [("enforcement-file", 10, 31, 60, 0, 24)]


def test_kdocs_browser_documents_only_returns_display_fields(monkeypatch):
    service = KDocsBrowserService(kdocs_settings(monkeypatch), FakeKDocsClient())

    result = service.list_documents("判决书", 30)
    data = result.model_dump()

    assert result.next_page_token == "next-001"
    assert result.items[0].name == "甲公司-张三判决书.pdf"
    assert result.items[0].modified_by == "法务A"
    assert result.items[0].size == 2048
    assert "private-user-id" not in str(data)
    assert "private-avatar" not in str(data)


def test_kdocs_browser_routes_are_readable_by_legal_and_auditor():
    paths = [
        "/api/v1/legal/kdocs-browser",
        "/api/v1/legal/kdocs-browser/tables/enforcement",
        "/api/v1/legal/kdocs-browser/documents",
    ]
    assert all(has_permission("legal", "GET", path) for path in paths)
    assert all(has_permission("auditor", "GET", path) for path in paths)
    assert not has_permission("legal", "POST", "/api/v1/legal/kdocs-browser")


def test_kdocs_browser_api_reports_mock_mode_without_calling_mcp(client):
    overview = client.get("/api/v1/legal/kdocs-browser")
    rows = client.get("/api/v1/legal/kdocs-browser/tables/enforcement")

    assert overview.status_code == 200
    assert overview.json()["data"]["configured"] is False
    assert rows.status_code == 400
    assert "尚未启用 real/mcp" in rows.json()["message"]
