import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from wecom_protocol_gateway.config import GatewayConfig


class NativeLabError(RuntimeError):
    pass


class NativeLabClient:
    """Isolated process boundary for clean-room interoperability experiments."""

    _methods = {
        "/login/createDevice",
        "/login/getLoginQrcode",
        "/login/checkLoginQrcode",
        "/login/verifyLoginQrcode",
        "/login/checkLogin",
        "/login/restoreDevice",
        "/login/logout",
        "/msg/sendText",
    }

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.state = NativeLabState(config.native_lab_state_path, config.state_key)

    async def invoke(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in self._methods:
            raise NativeLabError(f"native_lab 不支持方法：{method}")
        self._validate_scope(method, params)
        result = self._run("invoke", {"method": method, "params": params})
        self.state.record(method, params, result)
        return result

    async def probe(self) -> dict[str, Any]:
        result = self._run("probe", {})
        data = result.get("data")
        return data if isinstance(data, dict) else {"response": "invalid"}

    def status(self) -> dict[str, Any]:
        metadata = self.state.read()
        return {
            "backend": "native_lab",
            "ready": True,
            "online": metadata.get("online"),
            "stage": metadata.get("stage", "uninitialized"),
            "last_activity_at": metadata.get("last_activity_at"),
            "send_enabled": self.config.native_lab_allow_send,
            "scope": "test_only",
        }

    def _validate_scope(self, method: str, params: dict[str, Any]) -> None:
        guid = params.get("guid")
        if method != "/login/createDevice" and (
            not isinstance(guid, str)
            or not guid.startswith(self.config.native_lab_guid_prefix)
        ):
            raise NativeLabError("native_lab 仅允许实验 guid")
        if method != "/msg/sendText":
            return
        if not self.config.native_lab_allow_send:
            raise NativeLabError(
                "native_lab 真实发送默认关闭；完成登录和心跳验证后才能显式启用"
            )
        target = params.get("toId")
        content = params.get("content")
        if not isinstance(target, str) or not target.startswith(
            self.config.native_lab_room_prefix
        ):
            raise NativeLabError("native_lab 仅允许测试群")
        if not isinstance(content, str) or not content.startswith(
            self.config.native_lab_message_prefix
        ):
            raise NativeLabError("native_lab 测试消息缺少强制前缀")

    def _run(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "WECOM_NATIVE_LAB_STATE": str(self.config.native_lab_state_path),
        }
        try:
            completed = subprocess.run(
                [self.config.native_lab_binary, action],
                input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                capture_output=True,
                text=True,
                timeout=self.config.native_lab_timeout_seconds,
                check=False,
                shell=False,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise NativeLabError("native_lab 实验传输程序不存在") from exc
        except subprocess.TimeoutExpired as exc:
            raise NativeLabError("native_lab 实验传输超时") from exc
        if completed.returncode != 0:
            raise NativeLabError("native_lab 实验传输执行失败")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise NativeLabError("native_lab 实验传输返回非 JSON") from exc
        if not isinstance(result, dict):
            raise NativeLabError("native_lab 实验传输返回格式不正确")
        return result


class NativeLabState:
    def __init__(self, path: Path, state_key: str) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(state_key.encode("ascii"))

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            decrypted = self.fernet.decrypt(self.path.read_bytes())
            payload = json.loads(decrypted.decode("utf-8"))
        except (InvalidToken, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"stage": "state_error", "online": False}
        return payload if isinstance(payload, dict) else {}

    def record(
        self,
        method: str,
        params: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        previous = self.read()
        data = result.get("data")
        data = data if isinstance(data, dict) else {}
        result_code = result.get("code")
        if result_code not in (0, "0"):
            stage, online = "transport_error", False
        else:
            stage, online = _state_for(method, data, previous)
        guid = str(params.get("guid") or data.get("guid") or "")
        metadata = {
            "stage": stage,
            "online": online,
            "guid_hash": hashlib.sha256(guid.encode("utf-8")).hexdigest()
            if guid
            else previous.get("guid_hash"),
            "last_method": method,
            "last_result_code": result_code,
            "last_activity_at": datetime.now(UTC).isoformat(),
        }
        encrypted = self.fernet.encrypt(
            json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        )
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)


def _state_for(
    method: str,
    data: dict[str, Any],
    previous: dict[str, Any],
) -> tuple[str, bool]:
    online = data.get("online") is True or data.get("isOnline") in (1, "1", True)
    if method == "/login/createDevice":
        return "device_created", False
    if method == "/login/getLoginQrcode":
        return "qr_pending", False
    if method == "/login/checkLoginQrcode":
        if online:
            return "online", True
        stage = _qr_stage(data.get("status"))
        return stage or "login_pending", False
    if method == "/login/verifyLoginQrcode":
        if online:
            return "online", True
        if data.get("requiresVerification") is True:
            return "verification_required", False
        return "login_pending", False
    if method in {"/login/checkLogin", "/login/restoreDevice"}:
        return ("online", True) if online else ("login_pending", False)
    if method == "/login/logout":
        return "logged_out", False
    if method == "/msg/sendText":
        return "online", bool(previous.get("online"))
    return str(previous.get("stage") or "unknown"), bool(previous.get("online"))


def _qr_stage(status: Any) -> str | None:
    normalized = str(status).strip().lower()
    return {
        "0": "qr_pending",
        "no_scan": "qr_pending",
        "noscan": "qr_pending",
        "1": "qr_scanned",
        "scanned": "qr_scanned",
        "2": "qr_login_succeeded",
        "succeeded": "qr_login_succeeded",
        "3": "qr_failed",
        "failed": "qr_failed",
        "4": "qr_refused",
        "refused": "qr_refused",
        "5": "qr_scanned_wechat",
        "6": "qr_login_succeeded_wechat",
        "7": "qr_failed_wechat",
        "8": "qr_refused_wechat",
        "10": "verification_required",
        "needs_verification": "verification_required",
    }.get(normalized)
