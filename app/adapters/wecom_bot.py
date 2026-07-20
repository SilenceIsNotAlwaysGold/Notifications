import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.utils.datetime_utils import now_tz


@dataclass
class _BotChannelState:
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    last_attempt_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    sent_on: str = ""
    sent_count: int = 0
    group_sent_count: dict[str, int] = field(default_factory=dict)


class WeComBotAdapter:
    """HTTP client for the official WeCom AI Bot WebSocket sidecar."""

    _states_lock = threading.Lock()
    _states: dict[str, _BotChannelState] = {}

    def __init__(
        self,
        *,
        base_url: str | None,
        token: str | None,
        timeout_seconds: int,
        min_interval_seconds: float,
        daily_limit: int,
        group_daily_limit: int,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.daily_limit = daily_limit
        self.group_daily_limit = group_daily_limit
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def send_text(self, room_id: str, content: str) -> dict[str, Any]:
        missing = self._missing_settings()
        if missing:
            return self._failure(f"官方机器人 sidecar 缺少配置：{', '.join(missing)}")
        room_id = room_id.strip()
        content = content.strip()
        if not room_id:
            return self._failure("官方机器人目标群 ID 为空")
        if not content:
            return self._failure("官方机器人消息内容为空")
        if len(content.encode("utf-8")) > 2048:
            return self._failure("官方机器人消息内容超过 2048 个 UTF-8 字节")

        state = self._state()
        with state.send_lock:
            now = time.monotonic()
            if state.circuit_open_until > now:
                remaining = max(1, int(state.circuit_open_until - now))
                return self._failure(f"官方机器人发送熔断中，请在 {remaining} 秒后重试")

            today = now_tz().date().isoformat()
            if state.sent_on != today:
                state.sent_on = today
                state.sent_count = 0
                state.group_sent_count.clear()
            if state.sent_count >= self.daily_limit:
                return self._failure(f"官方机器人已达到每日发送上限 {self.daily_limit}")
            group_count = state.group_sent_count.get(room_id, 0)
            if group_count >= self.group_daily_limit:
                return self._failure(
                    f"群 {room_id} 已达到每日发送上限 {self.group_daily_limit}"
                )

            wait_seconds = self.min_interval_seconds - (now - state.last_attempt_at)
            if state.last_attempt_at and wait_seconds > 0:
                time.sleep(wait_seconds)

            result = self._post(room_id, content)
            state.last_attempt_at = time.monotonic()
            if result["success"]:
                state.consecutive_failures = 0
                state.sent_count += 1
                state.group_sent_count[room_id] = group_count + 1
            else:
                state.consecutive_failures += 1
                if state.consecutive_failures >= self.failure_threshold:
                    state.circuit_open_until = state.last_attempt_at + self.cooldown_seconds
                    state.consecutive_failures = 0
            return result

    def _post(self, room_id: str, content: str) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}/send-text",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json={"room_id": room_id, "content": content},
                timeout=self.timeout_seconds,
            )
            response_payload = self._parse_response(response)
            error = self._response_error(response.status_code, response_payload)
            return {
                "success": error is None,
                "mode": "wecom_bot",
                "status_code": response.status_code,
                "response": response_payload,
                "error": error,
            }
        except Exception as exc:
            return self._failure(f"官方机器人 sidecar 请求失败：{exc}")

    def _state(self) -> _BotChannelState:
        key = self.base_url
        with self._states_lock:
            return self._states.setdefault(key, _BotChannelState())

    def _missing_settings(self) -> list[str]:
        return [
            name
            for name, value in {
                "WECOM_BOT_SIDECAR_URL": self.base_url,
                "WECOM_BOT_SIDECAR_TOKEN": self.token,
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
            message = response_payload.get("error") or "sidecar 返回错误"
            return f"官方机器人 sidecar HTTP {status_code}：{message}"
        if not response_payload.get("success"):
            return str(response_payload.get("error") or "官方机器人发送失败")
        return None

    @staticmethod
    def _failure(error: str) -> dict[str, Any]:
        return {
            "success": False,
            "mode": "wecom_bot",
            "status_code": None,
            "response": None,
            "error": error,
        }

    @classmethod
    def reset_safety_state(cls) -> None:
        with cls._states_lock:
            cls._states.clear()
