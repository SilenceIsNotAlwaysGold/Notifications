import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from wecom_protocol_gateway.config import GatewayConfig


class OfficialCliError(RuntimeError):
    pass


class OfficialCliClient:
    """Safe async wrapper around the official WeCom CLI message capability."""

    _required_config_files = (".encryption_key", "bot.enc", "mcp_config.enc")

    def __init__(self, config: GatewayConfig) -> None:
        self.binary = config.official_cli_binary
        self.config_dir = config.official_cli_config_dir
        self.timeout_seconds = config.official_cli_timeout_seconds
        self.message_capability = "unknown"
        self._lock = asyncio.Lock()

    async def send_text(self, room_id: str, content: str) -> dict[str, Any]:
        if len(content.encode("utf-8")) > 2048:
            raise OfficialCliError("官方 CLI 文本消息不能超过 2048 字节")
        self._ensure_ready()
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
        async with self._lock:
            completed = await self._run(
                [self.binary, "msg", "send_message", "--json", payload]
            )
            business = self._business_result(completed)
        self.message_capability = "granted"
        return business

    async def probe(self) -> dict[str, Any]:
        self._ensure_ready()
        async with self._lock:
            completed = await self._run([self.binary, "msg", "--help"])
            self._check_process(completed)
        self.message_capability = "granted"
        return self.status()

    def status(self) -> dict[str, Any]:
        executable = self._resolve_binary()
        missing_files = [
            name for name in self._required_config_files if not (self.config_dir / name).is_file()
        ]
        ready = bool(executable) and not missing_files
        capability = self.message_capability if ready else "unavailable"
        return {
            "backend": "official_cli",
            "ready": ready,
            "online": None,
            "message_capability": capability,
            "binary_available": bool(executable),
            "config_available": not missing_files,
        }

    async def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["WECOM_CLI_CONFIG_DIR"] = str(self.config_dir)
        try:
            return await asyncio.to_thread(
                subprocess.run,
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
                shell=False,
            )
        except FileNotFoundError as exc:
            self.message_capability = "unavailable"
            raise OfficialCliError("未找到官方 wecom-cli 可执行文件") from exc
        except subprocess.TimeoutExpired as exc:
            self.message_capability = "error"
            raise OfficialCliError(
                f"官方 CLI 调用超过 {self.timeout_seconds:g} 秒"
            ) from exc
        except OSError as exc:
            self.message_capability = "error"
            raise OfficialCliError("官方 CLI 进程启动失败") from exc

    def _business_result(
        self, completed: subprocess.CompletedProcess[str]
    ) -> dict[str, Any]:
        self._check_process(completed)
        raw = completed.stdout.strip()
        if not raw:
            self.message_capability = "error"
            raise OfficialCliError("官方 CLI 未返回结果")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.message_capability = "error"
            raise OfficialCliError("官方 CLI 返回了无法解析的结果") from exc
        if not isinstance(parsed, dict):
            raise OfficialCliError("官方 CLI 返回格式不正确")

        if "errcode" in parsed:
            business = parsed
        else:
            business = self._extract_mcp_text(parsed)

        errcode = business.get("errcode")
        if errcode not in (None, 0):
            self.message_capability = "granted"
            errmsg = self._safe_text(business.get("errmsg")) or "企业微信返回错误"
            raise OfficialCliError(
                f"官方 CLI 返回 errcode={errcode}, errmsg={errmsg}"
            )
        return business

    def _check_process(self, completed: subprocess.CompletedProcess[str]) -> None:
        if completed.returncode == 0:
            return
        detail = self._safe_text(completed.stderr or completed.stdout)
        if "当前企业暂不支持授权机器人「消息」使用权限" in detail:
            self.message_capability = "denied"
            raise OfficialCliError(
                "官方 CLI 消息权限未授权："
                "企业微信服务端未向当前企业开放 msg 能力"
            )
        self.message_capability = "error"
        raise OfficialCliError(
            f"官方 CLI 返回退出码 {completed.returncode}"
            + (f"：{detail}" if detail else "")
        )

    def _ensure_ready(self) -> None:
        status = self.status()
        if not status["binary_available"]:
            raise OfficialCliError("未找到官方 wecom-cli 可执行文件")
        if not status["config_available"]:
            raise OfficialCliError(
                "官方 CLI 未初始化，配置目录需包含加密凭据和 MCP 配置"
            )

    def _resolve_binary(self) -> str | None:
        return shutil.which(self.binary)

    @classmethod
    def _extract_mcp_text(cls, parsed: dict[str, Any]) -> dict[str, Any]:
        result = parsed.get("result")
        if not isinstance(result, dict) or result.get("isError") is True:
            raise OfficialCliError("官方 CLI MCP 调用失败")
        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise OfficialCliError("官方 CLI 返回格式不正确")
        item = content[0]
        if not isinstance(item, dict) or item.get("type") != "text":
            raise OfficialCliError("官方 CLI 返回格式不正确")
        text = item.get("text")
        if not isinstance(text, str):
            raise OfficialCliError("官方 CLI 返回格式不正确")
        try:
            business = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OfficialCliError("官方 CLI 业务结果无法解析") from exc
        if not isinstance(business, dict):
            raise OfficialCliError("官方 CLI 业务结果格式不正确")
        return business

    @staticmethod
    def _safe_text(value: Any) -> str:
        return " ".join(str(value or "").strip().split())[:240]
