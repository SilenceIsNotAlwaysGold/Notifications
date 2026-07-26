import io

from openpyxl import Workbook
from sqlalchemy import select

from app.models.legal_case import LegalCase


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["日期", "原告", "被告", "案号", "缴费信息", "支付情况", "跟踪情况", "剩余缴费时间"])
    sheet.append(["2026-07-01", "甲公司", "张三", "(2026)粤0101民初100号", 36, "待支付", "已催促", "+7天"])
    sheet.append(["2026-07-02", "乙公司", None, "(2026)粤0101民初101号", 50, "待支付", None, "+7天"])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_case_xlsx_import_previews_before_confirming(client, db_session):
    response = client.post(
        "/api/v1/legal/cases/import-xlsx",
        data={"group_id": "payment_group", "confirm": "false"},
        files={"file": ("cases.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert data["creatable"] == 1
    assert data["invalid"] == 1
    assert data["items"][0]["due_date"] == "2026-07-08"
    assert db_session.scalar(select(LegalCase)) is None


def test_case_xlsx_import_confirm_creates_only_valid_new_cases(client, db_session):
    response = client.post(
        "/api/v1/legal/cases/import-xlsx",
        data={"group_id": "payment_group", "confirm": "true"},
        files={"file": ("cases.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["created"] == 1
    legal_case = db_session.scalar(select(LegalCase))
    assert legal_case.case_no == "(2026)粤0101民初100号"
    assert legal_case.plaintiff_name == "甲公司"
    assert legal_case.debtor_name == "张三"
    assert legal_case.group_id == "payment_group"
    assert legal_case.source == "spreadsheet_import"
    assert str(legal_case.total_amount) == "0.00"


def test_case_xlsx_import_normalizes_blank_tenant(client, db_session):
    response = client.post(
        "/api/v1/legal/cases/import-xlsx",
        data={"group_id": " payment_group ", "tenant_id": "  ", "confirm": "true"},
        files={"file": ("cases.xlsx", _workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    legal_case = db_session.scalar(select(LegalCase))
    assert legal_case.group_id == "payment_group"
    assert legal_case.tenant_id is None
