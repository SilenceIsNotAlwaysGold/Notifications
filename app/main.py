from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.scheduler import shutdown_scheduler, start_scheduler
from app.db.base import Base
from app.db.compat import ensure_sqlite_compat_columns
from app.db.session import engine
from app.middleware.audit_middleware import OperationAuditMiddleware


def initialize_database() -> None:
    settings = get_settings()
    if settings.db_auto_create:
        Base.metadata.create_all(bind=engine)
        ensure_sqlite_compat_columns(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.debug)
    initialize_database()
    start_scheduler()
    yield
    shutdown_scheduler()


settings = get_settings()
app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
app.add_middleware(OperationAuditMiddleware)
app.include_router(api_router, prefix="/api/v1")

admin_static_dir = Path(__file__).resolve().parent / "static" / "admin"


@app.get("/admin", include_in_schema=False)
def admin_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/")


if admin_static_dir.exists():
    app.mount("/admin", StaticFiles(directory=admin_static_dir, html=True), name="admin")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and {"code", "message", "data"} <= set(exc.detail.keys()):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"code": exc.status_code, "message": str(exc.detail), "data": None})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": 422, "message": "请求参数错误", "data": None})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"code": 500, "message": "服务内部错误", "data": None})
