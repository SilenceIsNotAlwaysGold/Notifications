import logging
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.response import raise_fail
from app.core.config import get_settings
from app.db.session import get_db
from app.services.wecomapi_room_cache_service import WeComApiRoomCacheService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wecomapi", tags=["wecomapi-callback"])
_RATE_LOCK = threading.Lock()
_REQUEST_TIMES: dict[str, deque[float]] = defaultdict(deque)


@router.post("/callback")
async def receive_wecomapi_callback(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _receive(request, db, path_secret=None)


@router.post("/callback/{path_secret}")
async def receive_wecomapi_callback_secret(path_secret: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return await _receive(request, db, path_secret=path_secret)


async def _receive(request: Request, db: Session, path_secret: str | None) -> dict[str, Any]:
    settings = get_settings()
    expected_path = (settings.wecomapi_callback_path_secret or "").strip()
    if expected_path and path_secret != expected_path:
        raise_fail("回调地址无效", code=404, status_code=404)
    _check_rate(request, settings.wecomapi_callback_rate_per_minute)

    payload = await _read_payload(request, settings.wecomapi_callback_max_bytes)
    events = _callback_events(payload)
    if events and settings.wecomapi_guid and any(str(event.get("guid") or "") != settings.wecomapi_guid for event in events):
        raise_fail("回调 GUID 不匹配", code=403, status_code=403)
    cache_service = WeComApiRoomCacheService(db)
    for event in events:
        logger.info(
            "wecomapi 回调已接收 guid=%s cmd=%s msg_type=%s request_id=%s "
            "msg_unique_id=%s from_room_id=%s",
            event.get("guid"),
            event.get("cmd"),
            event.get("msgType") or event.get("msg_type"),
            event.get("requestId") or event.get("request_id"),
            event.get("msgUniqueIdentifier") or event.get("msg_unique_identifier"),
            event.get("fromRoomId") or event.get("from_room_id"),
        )
        cache_service.record_event(event)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("wecomapi 回调群缓存写入失败")
    if not events:
        logger.info("wecomapi 回调已接收但不含可解析事件")
    return {"code": 0, "msg": "success", "data": {}}


async def _read_payload(request: Request, max_bytes: int) -> Any:
    body = await request.body()
    if len(body) > max_bytes:
        raise_fail("回调请求过大", code=413, status_code=413)
    try:
        return json.loads(body or b"{}")
    except Exception:
        logger.info("wecomapi 回调非 JSON payload bytes=%s", len(body))
        raise_fail("回调必须是 JSON", code=400, status_code=400)


def _check_rate(request: Request, limit: int) -> None:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _RATE_LOCK:
        bucket = _REQUEST_TIMES[client]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if len(bucket) >= limit:
            raise_fail("回调请求过于频繁", code=429, status_code=429)
        bucket.append(now)


def _callback_events(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return [payload] if any(key in payload for key in ("guid", "cmd", "msgType", "msg_type")) else []
