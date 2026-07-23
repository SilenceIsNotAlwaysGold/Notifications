from fastapi import APIRouter, Query

from app.api.v1.response import ok, raise_fail
from app.core.config import get_settings
from app.schemas.kdocs_browser import KDocsTarget
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
):
    try:
        data = KDocsBrowserService(get_settings()).list_rows(target, page, page_size)
    except ValueError as exc:
        raise_fail(str(exc), code=1400)
    except Exception:
        raise_fail("读取金山文档失败，请稍后重试", code=1502, status_code=502)
    return ok("金山表格内容查询成功", data)


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
