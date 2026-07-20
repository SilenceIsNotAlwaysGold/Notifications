#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.adapters.kdocs_mcp import KDocsMcpClient
from app.core.config import get_settings

ENFORCEMENT_HEADERS = [
    "代理人",
    "（法院组）代提交人",
    "原告主体",
    "被告",
    "身份证",
    "文书执行类型",
    "上传文件",
    "文书签发时间",
    "应还款时间",
    "履约情况",
    "提交情况",
    "申请强制时间",
    "所提交的法院",
    "法院审核状态",
    "审核意见",
    "材料是否寄出",
    "物流单号",
    "执行案号",
    "民初案号",
    "总金额",
    "已还欠款",
    "法官电话",
    "案件状态",
    "备注",
    "订单号",
]
COURT_HEADERS = [
    "法院",
    "开庭时间",
    "时间",
    "公司（原告）",
    "民初案号",
    "被告",
    "开庭方式",
    "跟进人",
    "交付时间",
    "回收时间",
    "代开庭邮寄单号",
    "金额",
    "代办事务",
    "代理人",
    "备注",
    "承办法官电话",
    "传票",
    "核对",
]


def _target_result(
    client: KDocsMcpClient,
    name: str,
    file_id: str,
    worksheet_id: int,
    expected_headers: list[str],
) -> dict[str, Any]:
    last_col = len(expected_headers) - 1
    sheet = client.get_sheet_info(file_id, worksheet_id)
    cells = client.get_range_data(
        file_id,
        worksheet_id,
        row_from=0,
        row_to=0,
        col_from=0,
        col_to=last_col,
    )
    headers = [None] * (last_col + 1)
    for cell in cells:
        col = int(cell.get("colFrom", cell.get("originCol", -1)))
        if 0 <= col <= last_col:
            headers[col] = cell.get("cellText") or cell.get("originalCellValue")
    return {
        "target": name,
        "file_id": file_id,
        "worksheet_id": worksheet_id,
        "sheet_name": sheet.get("sheetName"),
        "last_used_row": sheet.get("rowTo"),
        "headers": headers,
        "headers_match": headers == expected_headers,
    }


def main() -> int:
    settings = get_settings()
    if settings.kdocs_mode != "real" or settings.kdocs_transport != "mcp":
        print(json.dumps({"ok": False, "error": "需要 KDOCS_MODE=real 且 KDOCS_TRANSPORT=mcp"}, ensure_ascii=False))
        return 2

    required = {
        "KDOCS_ACCESS_TOKEN": settings.kdocs_access_token,
        "KDOCS_MCP_CLIENT_ID": settings.kdocs_mcp_client_id,
        "KDOCS_DRIVE_ID": settings.kdocs_drive_id,
        "KDOCS_ENFORCEMENT_FILE_ID": settings.kdocs_enforcement_file_id,
        "KDOCS_COURT_TIME_FILE_ID": settings.kdocs_court_time_file_id,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        print(json.dumps({"ok": False, "error": "配置缺失", "missing": missing}, ensure_ascii=False))
        return 2

    client = KDocsMcpClient(settings)
    try:
        targets = [
            _target_result(
                client,
                "强制执行进度",
                settings.kdocs_enforcement_file_id or "",
                settings.kdocs_enforcement_worksheet_id,
                ENFORCEMENT_HEADERS,
            ),
            _target_result(
                client,
                "开庭时间",
                settings.kdocs_court_time_file_id or "",
                settings.kdocs_court_time_worksheet_id,
                COURT_HEADERS,
            ),
        ]
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    ok = all(target["headers_match"] for target in targets)
    print(json.dumps({"ok": ok, "transport": "mcp", "targets": targets}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
