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


class CourtRowsFakeKDocsClient(FakeKDocsClient):
    def get_sheet_info(self, file_id, worksheet_id):
        if file_id == "court-file":
            return {"sheetId": worksheet_id, "sheetName": "开庭时间", "rowTo": 4}
        return super().get_sheet_info(file_id, worksheet_id)

    def get_range_data(self, file_id, worksheet_id, *, row_from, row_to, col_from, col_to):
        self.range_calls.append((file_id, worksheet_id, row_from, row_to, col_from, col_to))
        source = {
            1: ("2026-07-01 09:00", "张三", "线上"),
            2: ("2026-09-01 14:00", "李四", "线下"),
            3: ("待确认", "王五", "线上"),
            4: ("2026-08-01 10:30", "张六", "线上"),
        }
        cells = []
        for row in range(row_from, row_to + 1):
            hearing_time, defendant, court_mode = source[row]
            cells.extend(
                [
                    {"rowFrom": row, "colFrom": 1, "cellText": hearing_time},
                    {"rowFrom": row, "colFrom": 5, "cellText": defendant},
                    {"rowFrom": row, "colFrom": 6, "cellText": court_mode},
                ]
            )
        return cells


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


def test_kdocs_court_rows_filter_sort_and_paginate_across_full_sheet(monkeypatch):
    KDocsBrowserService._rows_cache.clear()
    client = CourtRowsFakeKDocsClient()
    service = KDocsBrowserService(kdocs_settings(monkeypatch), client)

    first_page = service.list_rows(
        "court",
        page=1,
        page_size=1,
        filter_column="被告",
        filter_value="张",
        sort_column="开庭时间",
        sort_order="desc",
    )
    second_page = service.list_rows(
        "court",
        page=2,
        page_size=1,
        filter_column="被告",
        filter_value="张",
        sort_column="开庭时间",
        sort_order="desc",
    )

    assert first_page.total == 2
    assert first_page.items[0].values["被告"] == "张六"
    assert second_page.items[0].values["被告"] == "张三"
    assert first_page.sort_order == "desc"


def test_kdocs_court_rows_filter_by_date_range_and_sort_ascending(monkeypatch):
    KDocsBrowserService._rows_cache.clear()
    service = KDocsBrowserService(kdocs_settings(monkeypatch), CourtRowsFakeKDocsClient())

    result = service.list_rows(
        "court",
        page=1,
        page_size=30,
        date_from="2026-08-01",
        date_to="2026-09-30",
        sort_column="开庭时间",
        sort_order="asc",
    )

    assert result.total == 2
    assert [item.values["被告"] for item in result.items] == ["张六", "李四"]


def test_kdocs_full_table_cache_is_reused_for_filter_and_sort(monkeypatch):
    KDocsBrowserService._rows_cache.clear()
    client = CourtRowsFakeKDocsClient()
    service = KDocsBrowserService(kdocs_settings(monkeypatch), client)

    service.list_rows("court", page=1, page_size=2, query="线上")
    service.list_rows("court", page=1, page_size=2, sort_column="被告", sort_order="asc")

    assert client.range_calls == [("court-file", 1, 1, 4, 0, 17)]


def test_kdocs_generic_filter_and_sort_reject_unknown_columns(monkeypatch):
    service = KDocsBrowserService(kdocs_settings(monkeypatch), FakeKDocsClient())

    try:
        service.list_rows("payment", page=1, page_size=30, sort_column="不存在")
    except ValueError as exc:
        assert str(exc) == "排序字段不存在"
    else:
        raise AssertionError("unknown sort columns must be rejected")


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
