from fastapi import APIRouter, Query

from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.schemas.kdocs_browser import KDocsRowUpdate, KDocsTarget
from app.services.kdocs_browser_service import KDocsBrowserService


router = APIRouter(prefix="/legal/kdocs-browser", tags=["legal-kdocs-browser"])


@router.get("")
def get_kdocs_browser_overview():
    return ok("金山文档状态查询成功", KDocsBrowserService(get_settings()).overview())


@router.get("/tables/{target}")
def list_kdocs_rows(
    target: KDocsTarget,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    query: str = Query(default="", max_length=100),
    filter_column: str = Query(default="", max_length=64),
    filter_value: str = Query(default="", max_length=100),
    sort_column: str = Query(default="", max_length=64),
    court_mode: str = Query(default="", max_length=32),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    refresh: bool = Query(default=False),
):
    try:
        data = KDocsBrowserService(get_settings()).list_rows(
            target,
            page,
            page_size,
            query=query.strip(),
            filter_column=filter_column.strip(),
            filter_value=filter_value.strip(),
            sort_column=sort_column.strip(),
            court_mode=court_mode.strip(),
            date_from=date_from,
            date_to=date_to,
            sort_order=sort_order,
            refresh=refresh,
        )
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    except Exception:
        raise_fail("读取金山文档失败，请稍后重试", code=1502, status_code=502)
    return ok("金山表格内容查询成功", data)


@router.patch("/tables/{target}/rows/{row_index}")
def update_kdocs_row(target: KDocsTarget, row_index: int, payload: KDocsRowUpdate):
    try:
        data = KDocsBrowserService(get_settings()).update_row(
            target,
            row_index,
            payload.values,
            payload.row_version,
        )
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    except Exception:
        raise_fail("更新金山表格失败，请刷新后重试", code=1502, status_code=502)
    return ok("金山表格行更新成功", data)


@router.delete("/tables/{target}/rows/{row_index}")
def delete_kdocs_row(
    target: KDocsTarget,
    row_index: int,
    row_version: str = Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
):
    try:
        data = KDocsBrowserService(get_settings()).delete_row(target, row_index, row_version)
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    except Exception:
        raise_fail("删除金山表格行失败，请刷新后重试", code=1502, status_code=502)
    return ok("金山表格行删除成功", data)


@router.get("/documents")
def list_kdocs_documents(
    query: str = Query(default="判决书", min_length=1, max_length=100),
    page_size: int = Query(default=30, ge=1, le=100),
    page_token: str | None = Query(default=None, max_length=256),
):
    try:
        data = KDocsBrowserService(get_settings()).list_documents(query.strip(), page_size, page_token)
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    except Exception:
        raise_fail("读取金山文件失败，请稍后重试", code=1502, status_code=502)
    return ok("金山文件查询成功", data)
