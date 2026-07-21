from typing import Any
from urllib.parse import urljoin

import httpx


class WeComSenderStatusClient:
    """Read and sanitize the self-hosted Android sender health response."""

    def __init__(self, *, base_url: str | None, timeout_seconds: float) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout_seconds = max(0.5, min(float(timeout_seconds), 3.0))

    def check(self) -> dict[str, Any]:
        if not self.base_url:
            return self._result("error", "发送端 sidecar 地址未配置")

        try:
            response = httpx.get(
                urljoin(self.base_url + "/", "wecom/finder/health"),
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            return self._result(
                "error",
                "发送端 sidecar 无法访问",
                error_type=type(exc).__name__,
            )

        if response.status_code >= 400:
            return self._result(
                "error",
                "发送端 sidecar 健康检查失败",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            return self._result(
                "error",
                "发送端 sidecar 返回格式不正确",
                status_code=response.status_code,
            )
        if not isinstance(payload, dict):
            return self._result(
                "error",
                "发送端 sidecar 返回格式不正确",
                status_code=response.status_code,
            )

        backend = payload.get("backend") if isinstance(payload.get("backend"), str) else "unknown"
        configured = payload.get("configured") is True
        target_count = self._nonnegative_int(payload.get("target_count"))
        device = payload.get("device") if isinstance(payload.get("device"), dict) else {}
        online = device.get("online") is True
        connected_at = device.get("connected_at") if isinstance(device.get("connected_at"), str) else None
        pending_commands = self._nonnegative_int(device.get("pending_commands"))
        fields = {
            "backend": backend,
            "configured": configured,
            "online": online,
            "connected_at": connected_at,
            "pending_commands": pending_commands,
            "target_count": target_count,
            "status_code": response.status_code,
        }

        if payload.get("status") != "ok":
            return self._result("error", "发送端 sidecar 状态异常", **fields)
        if backend == "mock":
            return self._result("degraded", "发送端为 Mock 模式，消息不会真实送达", **fields)
        if backend not in {"android", "worktool"}:
            return self._result("error", "发送端使用了未知运行模式", **fields)
        if not configured:
            return self._result("error", "发送端设备凭证未完整配置", **fields)
        if not online:
            return self._result("error", "Android 发送设备未连接", **fields)
        if target_count == 0:
            return self._result(
                "degraded",
                "发送设备在线，但尚未配置目标群白名单",
                **fields,
            )
        return self._result("ok", "Android 发送设备在线", **fields)

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    @staticmethod
    def _result(status: str, message: str, **fields: Any) -> dict[str, Any]:
        return {"status": status, "message": message, **fields}
