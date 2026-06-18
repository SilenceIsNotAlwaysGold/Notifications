from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config
from app.core.scheduler import scheduler
from app.db.session import engine
from app.models.api_key import ApiKey
from app.utils.datetime_utils import now_tz

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "time": now_tz().isoformat(),
    }


def _database_status() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "message": "connected"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _storage_status() -> dict[str, Any]:
    settings = get_settings()
    storage_dir = Path(settings.media_storage_dir)
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        probe_file = storage_dir / ".health_write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        return {
            "status": "ok",
            "media_storage_dir": str(storage_dir),
            "exists": True,
            "writable": True,
        }
    except Exception as exc:
        return {
            "status": "error",
            "media_storage_dir": str(storage_dir),
            "exists": storage_dir.exists(),
            "writable": False,
            "message": str(exc),
        }


def _scheduler_status() -> dict[str, Any]:
    jobs = []
    for job in scheduler.get_jobs():
        next_run_time = getattr(job, "next_run_time", None)
        jobs.append(
            {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run_time.isoformat() if next_run_time else None,
            }
        )
    return {"status": "ok", "running": scheduler.running, "jobs": jobs}


def _config_status() -> dict[str, Any]:
    config_result = validate_runtime_config(get_settings())
    if config_result["errors"]:
        status = "error"
    elif config_result["warnings"]:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "errors": config_result["errors"],
        "warnings": config_result["warnings"],
        "items": config_result["items"],
    }


@router.get("/detail")
def health_detail() -> dict[str, Any]:
    settings = get_settings()
    database = _database_status()
    config = _config_status()
    scheduler_status = _scheduler_status()
    storage = _storage_status()
    db_api_key_count = 0
    try:
        from sqlalchemy import select

        with engine.connect() as connection:
            db_api_key_count = len(list(connection.execute(select(ApiKey.id)).all()))
    except Exception:
        db_api_key_count = 0

    sections = [database, config, scheduler_status, storage]
    if any(section["status"] == "error" for section in sections):
        status = "error"
    elif any(section["status"] == "degraded" for section in sections):
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "database": database,
        "config": config,
        "scheduler": scheduler_status,
        "storage": storage,
        "auth": {
            "enabled": settings.auth_enabled,
            "rbac_enabled": settings.rbac_enabled,
            "admin_key_count": len(settings.admin_api_key_list),
            "db_api_key_count": db_api_key_count,
            "public_endpoints": settings.public_endpoint_list,
        },
        "tenant": {
            "enabled": settings.tenant_enabled,
        },
        "tenant_settings": {
            "enabled": settings.tenant_settings_enabled,
        },
    }
