import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.utils.datetime_utils import now_tz


@dataclass
class _ChannelState:
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    last_attempt_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    sent_on: str = ""
    sent_count: int = 0


class WeComApiAdapter:
    """HTTP client for the optional, non-official wecomapi protocol gateway."""

    _states_lock = threading.Lock()
    _states: dict[str, _ChannelState] = {}

    def __init__(
        self,
        *,
        base_url: str | None,
        api_path: str,
        token: str | None,
        guid: str | None,
        timeout_seconds: int,
        min_interval_seconds: float,
        daily_limit: int,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_path = f"/{api_path.lstrip('/')}"
        self.token = token or ""
        self.guid = guid or ""
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.daily_limit = daily_limit
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def send_text(self, room_id: str, content: str) -> dict[str, Any]:
        missing = self._missing_settings()
        if missing:
            return self._failure(f"wecomapi 缺少配置：{', '.join(missing)}")
        if not room_id.strip():
            return self._failure("wecomapi 目标群 ID 为空")
        if not content.strip():
            return self._failure("wecomapi 消息内容为空")

        state = self._state()
        with state.send_lock:
            now = time.monotonic()
            if state.circuit_open_until > now:
                remaining = max(1, int(state.circuit_open_until - now))
                return self._failure(f"wecomapi 发送熔断中，请在 {remaining} 秒后重试")

            today = now_tz().date().isoformat()
            if state.sent_on != today:
                state.sent_on = today
                state.sent_count = 0
            if state.sent_count >= self.daily_limit:
                return self._failure(f"wecomapi 已达到单账号每日发送上限 {self.daily_limit}")

            wait_seconds = self.min_interval_seconds - (now - state.last_attempt_at)
            if state.last_attempt_at and wait_seconds > 0:
                time.sleep(wait_seconds)

            result = self._post(room_id.strip(), content)
            state.last_attempt_at = time.monotonic()
            if result["success"]:
                state.consecutive_failures = 0
                state.sent_count += 1
            else:
                state.consecutive_failures += 1
                if state.consecutive_failures >= self.failure_threshold:
                    state.circuit_open_until = state.last_attempt_at + self.cooldown_seconds
                    state.consecutive_failures = 0
            return result

    def _post(self, room_id: str, content: str) -> dict[str, Any]:
        payload = {
            "method": "/msg/sendText",
            "params": {
                "guid": self.guid,
                "toId": room_id,
                "content": content,
            },
        }
        try:
            response = httpx.post(
                f"{self.base_url}{self.api_path}",
                headers={"WECOM-TOKEN": self.token, "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout_seconds,
            )
            response_payload = self._parse_response(response)
            error = self._response_error(response.status_code, response_payload)
            return {
                "success": error is None,
                "mode": "wecomapi",
                "status_code": response.status_code,
                "response": response_payload,
                "error": error,
            }
        except Exception as exc:
            return self._failure(f"wecomapi 请求失败：{exc}")

    def _state(self) -> _ChannelState:
        key = f"{self.base_url}|{self.guid}"
        with self._states_lock:
            return self._states.setdefault(key, _ChannelState())

    def _missing_settings(self) -> list[str]:
        return [
            name
            for name, value in {
                "WECOMAPI_BASE_URL": self.base_url,
                "WECOMAPI_TOKEN": self.token,
                "WECOMAPI_GUID": self.guid,
            }.items()
            if not value
        ]

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            parsed = response.json()
            return parsed if isinstance(parsed, dict) else {"data": parsed}
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _response_error(status_code: int, response_payload: dict[str, Any]) -> str | None:
        if status_code >= 400:
            return f"wecomapi HTTP {status_code}"
        code = response_payload.get("code")
        if code not in (None, 0):
            message = response_payload.get("msg") or response_payload.get("message") or "网关返回错误"
            return f"wecomapi 返回 code={code}, msg={message}"
        return None

    @staticmethod
    def _failure(error: str) -> dict[str, Any]:
        return {
            "success": False,
            "mode": "wecomapi",
            "status_code": None,
            "response": None,
            "error": error,
        }

    @classmethod
    def reset_safety_state(cls) -> None:
        """Reset in-process limiter state for tests and controlled maintenance."""
        with cls._states_lock:
            cls._states.clear()
