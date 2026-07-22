import secrets
from abc import ABC, abstractmethod
from typing import Any

import httpx

from wecom_protocol_gateway.config import GatewayConfig
from wecom_protocol_gateway.native_lab import NativeLabClient, NativeLabError
from wecom_protocol_gateway.official_cli import OfficialCliClient, OfficialCliError


class DriverError(RuntimeError):
    pass


class ProtocolDriver(ABC):
    @abstractmethod
    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict[str, Any]:
        raise NotImplementedError

    async def probe(self) -> dict[str, Any]:
        return self.status()


class MockProtocolDriver(ProtocolDriver):
    def __init__(self, account_guid: str) -> None:
        self.account_guid = account_guid
        self.room_names: dict[str, str] = {}

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "/login/createDevice":
            return _success({"guid": self.account_guid, "mock": True})
        if method == "/login/getLoginQrcode":
            return _success(
                {
                    "guid": self.account_guid,
                    "status": 2,
                    "qrCodeUrl": f"mock://wecom-login/{self.account_guid}",
                    "mock": True,
                }
            )
        if method in {
            "/login/checkLoginQrcode",
            "/login/verifyLoginQrcode",
            "/login/checkLogin",
            "/login/restoreDevice",
        }:
            return _success(
                {"guid": self.account_guid, "online": True, "status": 2, "mock": True}
            )
        if method == "/login/logout":
            return _success({"guid": self.account_guid, "online": False, "mock": True})
        if method == "/msg/sendText":
            return _success(
                {
                    "isSendSuccess": 1,
                    "msgServerId": f"mock-{secrets.token_hex(8)}",
                    "toId": params["toId"],
                    "mock": True,
                }
            )
        if method == "/room/modifyRoomName":
            self.room_names[params["roomId"]] = params["name"]
            return _success(
                {"roomId": params["roomId"], "name": params["name"], "mock": True}
            )
        raise DriverError(f"mock driver 不支持方法：{method}")

    def status(self) -> dict[str, Any]:
        return {"backend": "mock", "ready": True, "online": True}


class UpstreamProtocolDriver(ProtocolDriver):
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.config.request_timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.upstream_base_url}{self.config.upstream_api_path}",
                    headers={
                        self.config.upstream_token_header: self.config.upstream_token,
                        "Content-Type": "application/json",
                    },
                    json={"method": method, "params": params},
                )
        except httpx.HTTPError as exc:
            raise DriverError(f"上游协议驱动请求失败：{type(exc).__name__}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DriverError(f"上游协议驱动返回非 JSON，HTTP {response.status_code}") from exc
        if not isinstance(payload, dict):
            raise DriverError("上游协议驱动返回格式不正确")
        if response.status_code >= 400:
            raise DriverError(f"上游协议驱动 HTTP {response.status_code}")
        return payload

    def status(self) -> dict[str, Any]:
        return {
            "backend": "upstream",
            "ready": bool(self.config.upstream_base_url and self.config.upstream_token),
            "online": None,
        }


class OfficialCliProtocolDriver(ProtocolDriver):
    def __init__(self, config: GatewayConfig) -> None:
        self.client = OfficialCliClient(config)

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method != "/msg/sendText":
            raise DriverError(
                "official_cli 驱动仅支持文本发送，不支持设备登录或修改群名"
            )
        try:
            business = await self.client.send_text(params["toId"], params["content"])
        except OfficialCliError as exc:
            raise DriverError(str(exc)) from exc
        data: dict[str, Any] = {
            "isSendSuccess": 1,
            "toId": params["toId"],
            "transport": "official_cli",
        }
        for source, target in (
            ("msgid", "msgServerId"),
            ("message_id", "msgServerId"),
            ("request_id", "requestId"),
        ):
            if source in business and target not in data:
                data[target] = business[source]
        return _success(data)

    async def probe(self) -> dict[str, Any]:
        try:
            return await self.client.probe()
        except OfficialCliError as exc:
            raise DriverError(str(exc)) from exc

    def status(self) -> dict[str, Any]:
        return self.client.status()


class NativeLabProtocolDriver(ProtocolDriver):
    def __init__(self, config: GatewayConfig) -> None:
        self.client = NativeLabClient(config)

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return await self.client.invoke(method, params)
        except NativeLabError as exc:
            raise DriverError(str(exc)) from exc

    async def probe(self) -> dict[str, Any]:
        try:
            return await self.client.probe()
        except NativeLabError as exc:
            raise DriverError(str(exc)) from exc

    def status(self) -> dict[str, Any]:
        return self.client.status()


def build_driver(config: GatewayConfig) -> ProtocolDriver:
    if config.backend == "mock":
        return MockProtocolDriver(config.account_guid)
    if config.backend == "official_cli":
        return OfficialCliProtocolDriver(config)
    if config.backend == "native_lab":
        return NativeLabProtocolDriver(config)
    return UpstreamProtocolDriver(config)


def _success(data: dict[str, Any]) -> dict[str, Any]:
    return {"code": 0, "msg": "成功", "data": data}
