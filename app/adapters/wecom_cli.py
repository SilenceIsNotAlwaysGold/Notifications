import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.datetime_utils import now_tz


@dataclass
class _CliChannelState:
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    last_attempt_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    sent_on: str = ""
    sent_count: int = 0
    group_sent_count: dict[str, int] = field(default_factory=dict)


class WeComCliAdapter:
    """Client for the official WeCom CLI message service."""

    _room_id_pattern = re.compile(r"^(?:wr|wc)[A-Za-z0-9_-]{4,254}$")
    _states_lock = threading.Lock()
    _states: dict[str, _CliChannelState] = {}

    def __init__(
        self,
        *,
        binary: str,
        config_dir: str,
        timeout_seconds: int,
        min_interval_seconds: float,
        daily_limit: int,
        group_daily_limit: int,
        failure_threshold: int,
        cooldown_seconds: int,
    ) -> None:
        self.binary = binary.strip()
        raw_config_dir = config_dir.strip()
        self.config_dir = str(Path(raw_config_dir).expanduser()) if raw_config_dir else ""
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self.daily_limit = daily_limit
        self.group_daily_limit = group_daily_limit
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def send_text(self, room_id: str, content: str) -> dict[str, Any]:
        room_id = room_id.strip()
        if not self.binary:
            return self._failure("WECOM_CLI_BINARY 为空")
        if not self.config_dir:
            return self._failure("WECOM_CLI_CONFIG_DIR 为空")
        if not self._room_id_pattern.fullmatch(room_id):
            return self._failure("官方 CLI 目标群 ID 必须是 wr 或 wc 开头的群聊 ID")
        if not content.strip():
            return self._failure("官方 CLI 消息内容为空")
        if len(content.encode("utf-8")) > 2048:
            return self._failure("官方 CLI 文本消息不能超过 2048 字节")

        state = self._state()
        with state.send_lock:
            now = time.monotonic()
            if state.circuit_open_until > now:
                remaining = max(1, int(state.circuit_open_until - now))
                return self._failure(f"官方 CLI 发送熔断中，请在 {remaining} 秒后重试")

            today = now_tz().date().isoformat()
            if state.sent_on != today:
                state.sent_on = today
                state.sent_count = 0
                state.group_sent_count.clear()
            if state.sent_count >= self.daily_limit:
                return self._failure(f"官方 CLI 已达到每日发送上限 {self.daily_limit}")
            group_count = state.group_sent_count.get(room_id, 0)
            if group_count >= self.group_daily_limit:
                return self._failure(
                    f"官方 CLI 目标群已达到每日发送上限 {self.group_daily_limit}"
                )

            wait_seconds = self.min_interval_seconds - (now - state.last_attempt_at)
            if state.last_attempt_at and wait_seconds > 0:
                time.sleep(wait_seconds)

            result = self._run(room_id, content)
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

    def _run(self, room_id: str, content: str) -> dict[str, Any]:
        payload = json.dumps(
            {
                "chat_type": 2,
                "chatid": room_id,
                "msgtype": "text",
                "text": {"content": content},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        env = os.environ.copy()
        env["WECOM_CLI_CONFIG_DIR"] = self.config_dir
        try:
            completed = subprocess.run(
                [self.binary, "msg", "send_message", "--json", payload],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
                shell=False,
            )
        except FileNotFoundError:
            return self._failure(f"未找到官方 CLI 可执行文件：{self.binary}")
        except subprocess.TimeoutExpired:
            return self._failure(f"官方 CLI 调用超过 {self.timeout_seconds} 秒")
        except Exception as exc:
            return self._failure(f"官方 CLI 调用失败：{exc}")

        if completed.returncode != 0:
            detail = self._safe_error(completed.stderr or completed.stdout)
            return self._failure(
                f"官方 CLI 返回退出码 {completed.returncode}"
                + (f"：{detail}" if detail else "")
            )

        try:
            response_payload = self._parse_response(completed.stdout)
        except ValueError as exc:
            return self._failure(str(exc))

        errcode = response_payload.get("errcode")
        if errcode not in (None, 0):
            errmsg = response_payload.get("errmsg") or "企业微信返回错误"
            return self._failure(
                f"官方 CLI 返回 errcode={errcode}, errmsg={errmsg}",
                response=response_payload,
            )
        return {
            "success": True,
            "mode": "wecom_cli",
            "status_code": None,
            "response": response_payload,
            "error": None,
        }

    @classmethod
    def _parse_response(cls, stdout: str) -> dict[str, Any]:
        raw = stdout.strip()
        if not raw:
            raise ValueError("官方 CLI 未返回结果")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("官方 CLI 返回了无法解析的结果") from exc
        if not isinstance(parsed, dict):
            raise ValueError("官方 CLI 返回格式不正确")

        if "errcode" in parsed:
            return parsed
        if parsed.get("error"):
            raise ValueError("官方 CLI JSON-RPC 调用失败")

        result = parsed.get("result", {})
        if not isinstance(result, dict) or result.get("isError") is True:
            raise ValueError("官方 CLI MCP 调用失败")
        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise ValueError("官方 CLI 返回格式不正确")
        item = content[0]
        if not isinstance(item, dict) or item.get("type") != "text":
            raise ValueError("官方 CLI 返回格式不正确")
        text = item.get("text")
        if not isinstance(text, str):
            raise ValueError("官方 CLI 返回格式不正确")
        try:
            business = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("官方 CLI 业务结果无法解析") from exc
        if not isinstance(business, dict):
            raise ValueError("官方 CLI 业务结果格式不正确")
        return business

    def _state(self) -> _CliChannelState:
        with self._states_lock:
            return self._states.setdefault(self.config_dir, _CliChannelState())

    @staticmethod
    def _safe_error(value: str) -> str:
        return " ".join(value.strip().split())[:300]

    @staticmethod
    def _failure(error: str, response: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "success": False,
            "mode": "wecom_cli",
            "status_code": None,
            "response": response,
            "error": error,
        }

    @classmethod
    def reset_safety_state(cls) -> None:
        with cls._states_lock:
            cls._states.clear()
