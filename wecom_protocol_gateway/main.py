import asyncio
import logging
import re
import secrets
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from wecom_protocol_gateway.config import GatewayConfig, load_config
from wecom_protocol_gateway.drivers import DriverError, ProtocolDriver, build_driver
from wecom_protocol_gateway.store import GatewayStore

logger = logging.getLogger(__name__)

SUPPORTED_METHODS = {
    "/login/createDevice",
    "/login/getLoginQrcode",
    "/login/checkLoginQrcode",
    "/login/verifyLoginQrcode",
    "/login/checkLogin",
    "/login/restoreDevice",
    "/login/logout",
    "/msg/sendText",
    "/room/modifyRoomName",
}
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


class GatewayRequest(BaseModel):
    method: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)


class GatewayRuntime:
    def __init__(
        self,
        config: GatewayConfig,
        driver: ProtocolDriver,
        store: GatewayStore,
    ) -> None:
        self.config = config
        self.driver = driver
        self.store = store
        self._dispatch_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        target_id = params.get("toId") or params.get("roomId")
        try:
            result = await self.driver.invoke(method, params)
        except DriverError:
            self.store.add_operation(
                method=method,
                guid=str(params.get("guid") or self.config.account_guid),
                target_id=str(target_id) if target_id else None,
                success=False,
                result_code=None,
            )
            raise

        code = _result_code(result)
        self.store.add_operation(
            method=method,
            guid=str(params.get("guid") or self.config.account_guid),
            target_id=str(target_id) if target_id else None,
            success=code == 0,
            result_code=code,
        )
        return result

    async def dispatch_pending(self) -> None:
        if not self.config.business_callback_url or self._dispatch_lock.locked():
            return
        async with self._dispatch_lock:
            for key, payload in self.store.pending_events(limit=100):
                try:
                    async with httpx.AsyncClient(
                        timeout=self.config.request_timeout_seconds
                    ) as client:
                        response = await client.post(
                            self.config.business_callback_url,
                            headers={
                                "X-WECOM-GATEWAY-TOKEN": self.config.business_callback_token,
                                "Content-Type": "application/json",
                            },
                            json={"code": 0, "data": [payload]},
                        )
                    if response.status_code >= 400:
                        raise RuntimeError(f"HTTP {response.status_code}")
                except Exception as exc:
                    self.store.mark_failed(key, type(exc).__name__)
                    continue
                self.store.mark_delivered(key)

    async def retry_worker(self) -> None:
        while not self._stop_event.is_set():
            await self.dispatch_pending()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.config.callback_retry_seconds,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    runtime = GatewayRuntime(
        config=config,
        driver=build_driver(config),
        store=GatewayStore(config.state_db_path, config.state_key),
    )
    app.state.runtime = runtime
    worker = asyncio.create_task(runtime.retry_worker())
    try:
        yield
    finally:
        runtime.stop()
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="wecom-self-hosted-protocol-gateway", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    return {
        "status": "ok",
        "driver": runtime.driver.status(),
        "configured_guid": (
            _mask(runtime.config.account_guid) if runtime.config.account_guid else None
        ),
        "room_count": len(runtime.config.room_ids),
        "callback_configured": bool(runtime.config.business_callback_url),
        "callback_events": runtime.store.event_counts(),
        "state_key_persistent": runtime.config.state_key_persistent,
    }


@app.post("/api/qw/doApi")
@app.post("/wecom/finder/api")
async def gateway_api(
    request: Request,
    payload: GatewayRequest,
    wecom_token: str | None = Header(default=None, alias="WECOM-TOKEN"),
) -> dict[str, Any]:
    runtime = _runtime(request)
    _authorize(wecom_token, runtime.config.api_token)
    if payload.method not in SUPPORTED_METHODS:
        return {"code": 4001, "msg": f"不支持的方法：{payload.method}"}

    try:
        params = _validate_and_normalize(runtime.config, payload.method, payload.params)
        return await runtime.invoke(payload.method, params)
    except ValueError as exc:
        return {"code": 4002, "msg": str(exc)}
    except DriverError as exc:
        logger.warning("企业微信协议驱动调用失败 method=%s error=%s", payload.method, exc)
        return {"code": 5001, "msg": str(exc)}


@app.post("/callbacks/upstream")
async def upstream_callback(
    request: Request,
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
    callback_token: str | None = Header(
        default=None, alias="X-WECOM-UPSTREAM-CALLBACK-TOKEN"
    ),
) -> dict[str, Any]:
    runtime = _runtime(request)
    expected = runtime.config.upstream_callback_token
    if expected:
        _authorize(callback_token, expected)

    items = payload.get("data")
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="回调 data 必须是数组")
    accepted = 0
    duplicates = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        if runtime.store.add_event(item):
            accepted += 1
        else:
            duplicates += 1
    background_tasks.add_task(runtime.dispatch_pending)
    return {"code": 0, "accepted": accepted, "duplicates": duplicates}


@app.get("/api/qw/events")
async def callback_events(
    request: Request,
    wecom_token: str | None = Header(default=None, alias="WECOM-TOKEN"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    runtime = _runtime(request)
    _authorize(wecom_token, runtime.config.api_token)
    return {"data": runtime.store.event_metadata(limit=limit)}


@app.post("/api/qw/events/retry")
async def retry_callbacks(
    request: Request,
    background_tasks: BackgroundTasks,
    wecom_token: str | None = Header(default=None, alias="WECOM-TOKEN"),
) -> dict[str, Any]:
    runtime = _runtime(request)
    _authorize(wecom_token, runtime.config.api_token)
    background_tasks.add_task(runtime.dispatch_pending)
    return {"code": 0, "msg": "已安排重试"}


@app.post("/api/qw/capabilities/probe")
async def probe_capabilities(
    request: Request,
    wecom_token: str | None = Header(default=None, alias="WECOM-TOKEN"),
) -> dict[str, Any]:
    runtime = _runtime(request)
    _authorize(wecom_token, runtime.config.api_token)
    try:
        return {"code": 0, "msg": "成功", "data": await runtime.driver.probe()}
    except DriverError as exc:
        return {
            "code": 5001,
            "msg": str(exc),
            "data": runtime.driver.status(),
        }


def _validate_and_normalize(
    config: GatewayConfig,
    method: str,
    raw_params: dict[str, Any],
) -> dict[str, Any]:
    params = dict(raw_params)
    if method == "/login/createDevice":
        if config.account_guid:
            params.setdefault("guid", config.account_guid)
        return params

    if not config.account_guid:
        raise ValueError("网关尚未绑定 guid，请先创建设备并配置 WECOM_PROTOCOL_GUID")
    guid = _required_string(params, "guid", max_length=128)
    if not secrets.compare_digest(guid, config.account_guid):
        raise ValueError("guid 与网关账号不匹配")

    if method == "/msg/sendText":
        target = _required_string(params, "toId", max_length=128)
        params["toId"] = _resolve_room_id(config, target)
        _required_string(params, "content", max_length=4000)
    elif method == "/room/modifyRoomName":
        target = _required_string(params, "roomId", max_length=128)
        params["roomId"] = _resolve_room_id(config, target)
        _required_string(params, "name", max_length=64)
    elif method == "/login/verifyLoginQrcode":
        code = _required_string(params, "code", max_length=8)
        if not code.isdigit() or len(code) < 4:
            raise ValueError("登录验证码格式不正确")
    return params


def _resolve_room_id(config: GatewayConfig, target: str) -> str:
    resolved = config.room_ids.get(target)
    if resolved:
        return resolved
    if config.allow_raw_room_ids and _IDENTIFIER_PATTERN.fullmatch(target):
        return target
    raise ValueError(f"目标群 {target} 不在 WECOM_PROTOCOL_ROOM_IDS_JSON 白名单中")


def _required_string(params: dict[str, Any], name: str, *, max_length: int) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValueError(f"{name} 长度不能超过 {max_length}")
    params[name] = cleaned
    return cleaned


def _runtime(request: Request) -> GatewayRuntime:
    return request.app.state.runtime


def _authorize(provided: str | None, expected: str) -> None:
    if not secrets.compare_digest(provided or "", expected):
        raise HTTPException(status_code=401, detail="网关 token 无效")


def _result_code(result: dict[str, Any]) -> int | None:
    code = result.get("code")
    return int(code) if isinstance(code, int) else None


def _mask(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"
