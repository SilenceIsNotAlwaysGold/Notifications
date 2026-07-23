import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.schemas.wecomapi_settings import WeComApiLoginStatusOut, WeComApiSettingsOut, WeComApiSettingsUpdate


DEFAULT_PLATFORM_URL = "https://manager.wecomapi.com"
DEFAULT_ENV_FILE = Path(".env")


class WeComApiSettingsService:
    def __init__(self, settings: Settings | None = None, env_file: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.env_file = env_file or DEFAULT_ENV_FILE

    def current(self, callback_url: str) -> WeComApiSettingsOut:
        token = (self.settings.wecomapi_token or "").strip()
        guid = (self.settings.wecomapi_guid or "").strip()
        return WeComApiSettingsOut(
            send_mode=self.settings.wecom_send_mode,
            base_url=self.settings.wecomapi_base_url,
            api_path=self.settings.wecomapi_api_path,
            token_header=self.settings.wecomapi_token_header,
            has_token=bool(token),
            token_mask=self.settings.secret_value_mask if token else None,
            guid=guid or None,
            has_guid=bool(guid),
            callback_url=callback_url,
            callback_auth_enabled=bool((self.settings.wecomapi_callback_path_secret or "").strip()),
            platform_url=DEFAULT_PLATFORM_URL,
        )

    def update(self, payload: WeComApiSettingsUpdate) -> None:
        updates = self._payload_to_env(payload)
        if not updates:
            return
        self._write_env(updates)
        os.environ.update(updates)
        get_settings.cache_clear()
        self.settings = get_settings()

    def check_login(self) -> WeComApiLoginStatusOut:
        base_url = (self.settings.wecomapi_base_url or "").strip().rstrip("/")
        api_path = "/" + self.settings.wecomapi_api_path.strip().lstrip("/")
        token = (self.settings.wecomapi_token or "").strip()
        guid = (self.settings.wecomapi_guid or "").strip()
        missing = [
            key
            for key, value in {
                "WECOMAPI_BASE_URL": base_url,
                "WECOMAPI_TOKEN": token,
                "WECOMAPI_GUID": guid,
            }.items()
            if not value
        ]
        endpoint = f"{base_url}{api_path}" if base_url else None
        if missing:
            return WeComApiLoginStatusOut(
                configured=False,
                online=False,
                stage="not_configured",
                missing=missing,
                checked_endpoint=endpoint,
            )

        try:
            response = httpx.post(
                endpoint,
                headers={self.settings.wecomapi_token_header: token, "Content-Type": "application/json"},
                json={"method": "/login/checkLogin", "params": {"guid": guid}},
                timeout=self.settings.wecom_timeout_seconds,
            )
            payload = response.json()
        except httpx.HTTPError as exc:
            return WeComApiLoginStatusOut(
                configured=True,
                online=False,
                stage="request_failed",
                vendor_message=f"{type(exc).__name__}",
                checked_endpoint=endpoint,
            )
        except ValueError:
            return WeComApiLoginStatusOut(
                configured=True,
                online=False,
                stage="invalid_response",
                vendor_message=f"HTTP {response.status_code} 返回非 JSON",
                checked_endpoint=endpoint,
            )

        if not isinstance(payload, dict):
            return WeComApiLoginStatusOut(
                configured=True,
                online=False,
                stage="invalid_response",
                vendor_message="第三方平台返回格式不正确",
                checked_endpoint=endpoint,
            )

        data = self._data(payload)
        online = self._is_online(data)
        vendor_code = payload.get("code")
        vendor_message = self._vendor_message(payload)
        if response.status_code >= 400:
            stage = "remote_error"
        elif vendor_code not in (None, 0, "0"):
            stage = "login_expired" if self._looks_expired(vendor_message) else "remote_error"
        elif online:
            stage = "logged_in"
        else:
            stage = "logged_out"
        return WeComApiLoginStatusOut(
            configured=True,
            online=online,
            stage=stage,
            account_name=self._first_text(data, "name", "userName", "nickname", "alias"),
            vendor_code=vendor_code,
            vendor_message=vendor_message,
            checked_endpoint=endpoint,
            raw_data=self._safe_data(data),
        )

    @staticmethod
    def _payload_to_env(payload: WeComApiSettingsUpdate) -> dict[str, str]:
        mapping = {
            "send_mode": "WECOM_SEND_MODE",
            "base_url": "WECOMAPI_BASE_URL",
            "api_path": "WECOMAPI_API_PATH",
            "token_header": "WECOMAPI_TOKEN_HEADER",
            "token": "WECOMAPI_TOKEN",
            "guid": "WECOMAPI_GUID",
        }
        updates: dict[str, str] = {}
        for field, env_key in mapping.items():
            if field in payload.model_fields_set:
                value = getattr(payload, field)
                updates[env_key] = "" if value is None else str(value).strip()
        return updates

    def _write_env(self, updates: dict[str, str]) -> None:
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = self.env_file.read_text(encoding="utf-8").splitlines() if self.env_file.exists() else []
        seen: set[str] = set()
        next_lines: list[str] = []
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                next_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in updates:
                next_lines.append(f"{key}={self._format_env_value(updates[key])}")
                seen.add(key)
            else:
                next_lines.append(line)
        for key, value in updates.items():
            if key not in seen:
                next_lines.append(f"{key}={self._format_env_value(value)}")
        if self.env_file.exists():
            backup = self.env_file.with_name(f"{self.env_file.name}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.copy2(self.env_file, backup)
        self.env_file.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _format_env_value(value: str) -> str:
        if value == "":
            return ""
        if any(character.isspace() or character in {'"', "'", "#"} for character in value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value

    @staticmethod
    def _data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _is_online(data: dict[str, Any]) -> bool:
        for key in ("online", "isOnline", "isLogin", "loggedIn"):
            if key in data:
                value = data[key]
                return value is True or value in (1, "1", "true", "online")
        if data.get("status") in (2, "2", "online", "logged_in"):
            return True
        return any(
            isinstance(data.get(key), (str, int)) and str(data[key]).strip()
            for key in ("userId", "userName", "nickname", "alias", "name")
        )

    @staticmethod
    def _vendor_message(payload: dict[str, Any]) -> str | None:
        for key in ("msg", "message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _looks_expired(message: str | None) -> bool:
        if not message:
            return False
        return any(word in message for word in ("过期", "重新登录", "未登录", "登录态"))

    @staticmethod
    def _first_text(data: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _safe_data(data: dict[str, Any]) -> dict[str, Any]:
        allowed = ("online", "isOnline", "isLogin", "loggedIn", "name", "userName", "nickname", "alias", "status")
        return {key: data[key] for key in allowed if key in data}
