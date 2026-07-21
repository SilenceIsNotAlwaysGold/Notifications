import asyncio
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


@dataclass(frozen=True)
class SenderConfig:
    backend: str
    api_token: str
    robot_id: str
    targets: dict[str, str]
    allow_raw_targets: bool
    command_timeout_seconds: float


def load_config() -> SenderConfig:
    backend = os.getenv("WECOM_SENDER_BACKEND", "mock").strip().lower()
    if backend not in {"mock", "android", "worktool"}:
        raise RuntimeError("WECOM_SENDER_BACKEND 只支持 mock、android 或 worktool")

    targets_raw = os.getenv("WECOM_SENDER_TARGETS_JSON", "{}").strip() or "{}"
    try:
        parsed_targets = json.loads(targets_raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("WECOM_SENDER_TARGETS_JSON 不是合法 JSON") from exc
    if not isinstance(parsed_targets, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in parsed_targets.items()
    ):
        raise RuntimeError("WECOM_SENDER_TARGETS_JSON 必须是字符串到字符串的映射")

    config = SenderConfig(
        backend=backend,
        api_token=(
            os.getenv("WECOM_SENDER_API_TOKEN")
            or os.getenv("WECOMAPI_TOKEN")
            or ""
        ).strip(),
        robot_id=(
            os.getenv("WECOM_SENDER_ROBOT_ID")
            or os.getenv("WECOMAPI_GUID")
            or ""
        ).strip(),
        targets={key.strip(): value.strip() for key, value in parsed_targets.items()},
        allow_raw_targets=os.getenv("WECOM_SENDER_ALLOW_RAW_TARGETS", "false").lower()
        in {"1", "true", "yes", "on"},
        command_timeout_seconds=float(
            os.getenv("WECOM_SENDER_COMMAND_TIMEOUT_SECONDS", "45")
        ),
    )
    if config.command_timeout_seconds <= 0:
        raise RuntimeError("WECOM_SENDER_COMMAND_TIMEOUT_SECONDS 必须大于 0")
    if config.backend in {"android", "worktool"}:
        if len(config.api_token) < 24:
            raise RuntimeError("Android 模式的 WECOM_SENDER_API_TOKEN 至少 24 位")
        if not _DEVICE_ID_PATTERN.fullmatch(config.robot_id):
            raise RuntimeError(
                "Android 模式的 WECOM_SENDER_ROBOT_ID 必须为 24-128 位安全标识"
            )
    return config


class GatewayParams(BaseModel):
    guid: str = Field(min_length=1)
    toId: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=4000)


class GatewayRequest(BaseModel):
    method: str
    params: GatewayParams


@dataclass
class DeviceConnection:
    websocket: WebSocket
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)


class SenderConnectionManager:
    def __init__(self) -> None:
        self._devices: dict[str, DeviceConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, robot_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            previous = self._devices.pop(robot_id, None)
            if previous is not None:
                await previous.websocket.close(code=1012, reason="replaced by a new connection")
                self._fail_pending(previous, "设备连接已被替换")
            self._devices[robot_id] = DeviceConnection(websocket=websocket)
        logger.info("企业微信发送设备已连接 robot_id=%s", _mask_identifier(robot_id))

    async def unregister(self, robot_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            connection = self._devices.get(robot_id)
            if connection is None or connection.websocket is not websocket:
                return
            self._devices.pop(robot_id, None)
            self._fail_pending(connection, "企业微信发送设备已离线")
        logger.info("企业微信发送设备已离线 robot_id=%s", _mask_identifier(robot_id))

    async def send_text(
        self,
        *,
        robot_id: str,
        group_name: str,
        content: str,
        timeout_seconds: float,
    ) -> tuple[str, dict[str, Any]]:
        async with self._lock:
            connection = self._devices.get(robot_id)
        if connection is None:
            raise RuntimeError("企业微信发送设备不在线")

        message_id = secrets.token_hex(16)
        command = _device_text_command(message_id, group_name, content)
        loop = asyncio.get_running_loop()
        completion: asyncio.Future[dict[str, Any]] = loop.create_future()

        async with connection.send_lock:
            connection.pending[message_id] = completion
            try:
                await connection.websocket.send_json(command)
                result = await asyncio.wait_for(completion, timeout=timeout_seconds)
            except TimeoutError as exc:
                raise RuntimeError("等待企业微信设备执行回执超时") from exc
            finally:
                connection.pending.pop(message_id, None)
        return message_id, result

    async def handle_device_message(self, robot_id: str, payload: dict[str, Any]) -> None:
        if payload.get("socketType") != 3:
            return
        message_id = str(payload.get("messageId") or "")
        if not message_id:
            return
        async with self._lock:
            connection = self._devices.get(robot_id)
        if connection is None:
            return
        completion = connection.pending.get(message_id)
        if completion is not None and not completion.done():
            completion.set_result(payload)

    async def status(self, robot_id: str) -> dict[str, Any]:
        async with self._lock:
            connection = self._devices.get(robot_id)
        return {
            "online": connection is not None,
            "connected_at": (
                connection.connected_at.isoformat() if connection is not None else None
            ),
            "pending_commands": len(connection.pending) if connection is not None else 0,
        }

    async def reset(self) -> None:
        async with self._lock:
            devices = list(self._devices.values())
            self._devices.clear()
        for connection in devices:
            self._fail_pending(connection, "发送网关已重置")

    @staticmethod
    def _fail_pending(connection: DeviceConnection, reason: str) -> None:
        for completion in connection.pending.values():
            if not completion.done():
                completion.set_exception(RuntimeError(reason))
        connection.pending.clear()


def _device_text_command(message_id: str, group_name: str, content: str) -> dict[str, Any]:
    return {
        "socketType": 2,
        "messageId": message_id,
        "apiSend": 1,
        "encryptType": 0,
        "encryptedList": "",
        "list": [
            {
                "type": 203,
                "roomType": 1,
                "titleList": [group_name],
                "receivedContent": content,
                "maxRetryCount": 1,
            }
        ],
    }


def _resolve_group_name(config: SenderConfig, target_id: str) -> str:
    group_name = config.targets.get(target_id)
    if group_name:
        return group_name
    if config.allow_raw_targets:
        return target_id
    raise ValueError(f"目标 {target_id} 不在 WECOM_SENDER_TARGETS_JSON 白名单中")


def _extract_callback(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("list")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return {"errorCode": 5000, "errorReason": "设备回执格式不正确"}
    return items[0]


def _mask_identifier(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


sender_manager = SenderConnectionManager()
app = FastAPI(title="wecom-self-hosted-sender-sidecar")


@app.get("/wecom/finder/health")
async def health() -> dict[str, Any]:
    config = load_config()
    device_status = await sender_manager.status(config.robot_id)
    return {
        "status": "ok",
        "backend": config.backend,
        "configured": bool(config.api_token and config.robot_id),
        "device": device_status,
        "target_count": len(config.targets),
    }


@app.post("/wecom/finder/api")
async def gateway_api(
    payload: GatewayRequest,
    wecom_token: str | None = Header(default=None, alias="WECOM-TOKEN"),
) -> dict[str, Any]:
    config = load_config()
    if not config.api_token:
        raise HTTPException(status_code=503, detail="WECOM_SENDER_API_TOKEN 未配置")
    if not secrets.compare_digest(wecom_token or "", config.api_token):
        raise HTTPException(status_code=401, detail="发送网关 token 无效")
    if not config.robot_id:
        raise HTTPException(status_code=503, detail="WECOM_SENDER_ROBOT_ID 未配置")
    if payload.method != "/msg/sendText":
        return {"code": 4001, "msg": f"不支持的方法：{payload.method}"}
    if not secrets.compare_digest(payload.params.guid, config.robot_id):
        return {"code": 4003, "msg": "发送设备 ID 不匹配"}

    try:
        group_name = _resolve_group_name(config, payload.params.toId.strip())
    except ValueError as exc:
        return {"code": 4004, "msg": str(exc)}

    if config.backend == "mock":
        message_id = f"mock-{secrets.token_hex(8)}"
        logger.info(
            "mock 企业微信外部群发送 target=%s content_length=%s",
            payload.params.toId,
            len(payload.params.content),
        )
        return {
            "code": 0,
            "msg": "成功",
            "data": {
                "msgId": message_id,
                "targetId": payload.params.toId,
                "groupName": group_name,
                "mock": True,
            },
        }

    try:
        message_id, device_payload = await sender_manager.send_text(
            robot_id=config.robot_id,
            group_name=group_name,
            content=payload.params.content,
            timeout_seconds=config.command_timeout_seconds,
        )
    except RuntimeError as exc:
        return {"code": 5001, "msg": str(exc)}

    callback = _extract_callback(device_payload)
    error_code = callback.get("errorCode")
    if error_code not in (None, 0):
        return {
            "code": int(error_code),
            "msg": callback.get("errorReason") or "企业微信设备执行失败",
            "data": {"msgId": message_id, "callback": callback},
        }
    return {
        "code": 0,
        "msg": "成功",
        "data": {
            "msgId": message_id,
            "targetId": payload.params.toId,
            "groupName": group_name,
            "callback": callback,
        },
    }


@app.websocket("/webserver/wework/{robot_id}")
async def sender_device_socket(websocket: WebSocket, robot_id: str) -> None:
    config = load_config()
    if (
        config.backend not in {"android", "worktool"}
        or not config.robot_id
        or not secrets.compare_digest(robot_id, config.robot_id)
    ):
        await websocket.close(code=1008, reason="sender device is not authorized")
        return

    await sender_manager.register(robot_id, websocket)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("忽略无法解析的企业微信设备消息")
                continue
            if isinstance(payload, dict):
                await sender_manager.handle_device_message(robot_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await sender_manager.unregister(robot_id, websocket)
