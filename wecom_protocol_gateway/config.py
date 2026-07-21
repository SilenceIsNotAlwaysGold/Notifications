import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet


_HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")


@dataclass(frozen=True)
class GatewayConfig:
    backend: str
    api_token: str
    account_guid: str
    room_ids: dict[str, str]
    allow_raw_room_ids: bool
    state_db_path: Path
    state_key: str
    state_key_persistent: bool
    upstream_base_url: str
    upstream_api_path: str
    upstream_token: str
    upstream_token_header: str
    upstream_callback_token: str
    official_cli_binary: str
    official_cli_config_dir: Path
    official_cli_timeout_seconds: float
    business_callback_url: str
    business_callback_token: str
    request_timeout_seconds: float
    callback_retry_seconds: float


def load_config() -> GatewayConfig:
    backend = os.getenv("WECOM_PROTOCOL_BACKEND", "mock").strip().lower()
    if backend not in {"mock", "official_cli", "upstream"}:
        raise RuntimeError(
            "WECOM_PROTOCOL_BACKEND 只支持 mock、official_cli 或 upstream"
        )

    room_ids = _load_string_mapping("WECOM_PROTOCOL_ROOM_IDS_JSON")
    state_key = os.getenv("WECOM_PROTOCOL_STATE_KEY", "").strip()
    state_key_persistent = bool(state_key)
    if not state_key:
        state_key = Fernet.generate_key().decode("ascii")
    try:
        Fernet(state_key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("WECOM_PROTOCOL_STATE_KEY 不是合法 Fernet key") from exc

    upstream_base_url = os.getenv("WECOM_PROTOCOL_UPSTREAM_BASE_URL", "").strip().rstrip("/")
    upstream_token_header = os.getenv(
        "WECOM_PROTOCOL_UPSTREAM_TOKEN_HEADER", "WECOM-TOKEN"
    ).strip()
    if not _HEADER_NAME_PATTERN.fullmatch(upstream_token_header):
        raise RuntimeError("WECOM_PROTOCOL_UPSTREAM_TOKEN_HEADER 格式不正确")

    config = GatewayConfig(
        backend=backend,
        api_token=os.getenv("WECOM_PROTOCOL_API_TOKEN", "").strip(),
        account_guid=os.getenv("WECOM_PROTOCOL_GUID", "").strip(),
        room_ids=room_ids,
        allow_raw_room_ids=_env_bool("WECOM_PROTOCOL_ALLOW_RAW_ROOM_IDS", False),
        state_db_path=Path(
            os.getenv("WECOM_PROTOCOL_STATE_DB", "./storage/wecom-protocol/gateway.db")
        ).expanduser(),
        state_key=state_key,
        state_key_persistent=state_key_persistent,
        upstream_base_url=upstream_base_url,
        upstream_api_path=(
            "/" + os.getenv("WECOM_PROTOCOL_UPSTREAM_API_PATH", "/api/qw/doApi").lstrip("/")
        ),
        upstream_token=os.getenv("WECOM_PROTOCOL_UPSTREAM_TOKEN", "").strip(),
        upstream_token_header=upstream_token_header,
        upstream_callback_token=os.getenv(
            "WECOM_PROTOCOL_UPSTREAM_CALLBACK_TOKEN", ""
        ).strip(),
        official_cli_binary=os.getenv(
            "WECOM_PROTOCOL_OFFICIAL_CLI_BINARY", "wecom-cli"
        ).strip(),
        official_cli_config_dir=Path(
            os.getenv("WECOM_PROTOCOL_OFFICIAL_CLI_CONFIG_DIR", "~/.config/wecom")
        ).expanduser(),
        official_cli_timeout_seconds=float(
            os.getenv("WECOM_PROTOCOL_OFFICIAL_CLI_TIMEOUT_SECONDS", "35")
        ),
        business_callback_url=os.getenv("WECOM_PROTOCOL_CALLBACK_URL", "").strip(),
        business_callback_token=os.getenv(
            "WECOM_PROTOCOL_CALLBACK_TOKEN", ""
        ).strip(),
        request_timeout_seconds=float(
            os.getenv("WECOM_PROTOCOL_REQUEST_TIMEOUT_SECONDS", "15")
        ),
        callback_retry_seconds=float(
            os.getenv("WECOM_PROTOCOL_CALLBACK_RETRY_SECONDS", "15")
        ),
    )
    _validate_config(config)
    return config


def _load_string_mapping(name: str) -> dict[str, str]:
    raw = os.getenv(name, "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} 不是合法 JSON") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in parsed.items()
    ):
        raise RuntimeError(f"{name} 必须是字符串到字符串的映射")
    return {
        key.strip(): value.strip()
        for key, value in parsed.items()
        if key.strip() and value.strip()
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _validate_config(config: GatewayConfig) -> None:
    if not config.api_token:
        raise RuntimeError("WECOM_PROTOCOL_API_TOKEN 未配置")
    if config.backend == "mock" and not config.account_guid:
        raise RuntimeError("WECOM_PROTOCOL_GUID 未配置")
    if config.request_timeout_seconds <= 0:
        raise RuntimeError("WECOM_PROTOCOL_REQUEST_TIMEOUT_SECONDS 必须大于 0")
    if config.callback_retry_seconds <= 0:
        raise RuntimeError("WECOM_PROTOCOL_CALLBACK_RETRY_SECONDS 必须大于 0")

    if config.backend == "official_cli":
        missing = [
            name
            for name, value in {
                "WECOM_PROTOCOL_GUID": config.account_guid,
                "WECOM_PROTOCOL_OFFICIAL_CLI_BINARY": config.official_cli_binary,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"official_cli 模式缺少配置：{', '.join(missing)}")
        if config.official_cli_timeout_seconds <= 0:
            raise RuntimeError(
                "WECOM_PROTOCOL_OFFICIAL_CLI_TIMEOUT_SECONDS 必须大于 0"
            )

    if config.backend == "upstream":
        missing = [
            name
            for name, value in {
                "WECOM_PROTOCOL_UPSTREAM_BASE_URL": config.upstream_base_url,
                "WECOM_PROTOCOL_UPSTREAM_TOKEN": config.upstream_token,
                "WECOM_PROTOCOL_UPSTREAM_CALLBACK_TOKEN": (
                    config.upstream_callback_token
                ),
                "WECOM_PROTOCOL_STATE_KEY": (
                    config.state_key if config.state_key_persistent else ""
                ),
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"upstream 模式缺少配置：{', '.join(missing)}")
        _validate_http_url(config.upstream_base_url, "WECOM_PROTOCOL_UPSTREAM_BASE_URL")

    if config.business_callback_url:
        _validate_http_url(config.business_callback_url, "WECOM_PROTOCOL_CALLBACK_URL")
        if not config.business_callback_token:
            raise RuntimeError(
                "配置 WECOM_PROTOCOL_CALLBACK_URL 时必须同时配置 WECOM_PROTOCOL_CALLBACK_TOKEN"
            )


def _validate_http_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{name} 必须是合法 http 或 https URL")
