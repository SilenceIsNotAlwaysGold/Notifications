import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import Settings
from app.core.permissions import ROLES


def _add_item(result: dict[str, Any], name: str, status: str, message: str) -> None:
    result["items"].append({"name": name, "status": status, "message": message})
    if status == "error":
        result["errors"].append(message)
    elif status == "warning":
        result["warnings"].append(message)


def _validate_media_storage(settings: Settings, result: dict[str, Any]) -> None:
    storage_dir = Path(settings.media_storage_dir)
    if storage_dir.exists() and not storage_dir.is_dir():
        _add_item(result, "MEDIA_STORAGE_DIR", "error", "MEDIA_STORAGE_DIR 已存在但不是目录")
        return

    created = False
    if not storage_dir.exists():
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
            created = True
        except Exception as exc:
            _add_item(result, "MEDIA_STORAGE_DIR", "error", f"MEDIA_STORAGE_DIR 不存在且无法创建：{exc}")
            return

    try:
        probe_file = storage_dir / ".write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except Exception as exc:
        _add_item(result, "MEDIA_STORAGE_DIR", "error", f"MEDIA_STORAGE_DIR 不可写：{exc}")
        return

    if created:
        _add_item(result, "MEDIA_STORAGE_DIR", "warning", "MEDIA_STORAGE_DIR 不存在，已自动创建")
    else:
        _add_item(result, "MEDIA_STORAGE_DIR", "ok", "MEDIA_STORAGE_DIR 存在且可写")


def _validate_backup_storage(settings: Settings, result: dict[str, Any]) -> None:
    backup_dir = Path(settings.ops_backup_dir)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        probe_file = backup_dir / ".write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except Exception as exc:
        _add_item(result, "OPS_BACKUP_DIR", "error", f"OPS_BACKUP_DIR 不可写：{exc}")
        return
    _add_item(result, "OPS_BACKUP_DIR", "ok", "OPS_BACKUP_DIR 存在且可写")


def _validate_database_url(settings: Settings, result: dict[str, Any]) -> None:
    database_url = settings.database_url
    if not database_url:
        _add_item(result, "DATABASE_URL", "error", "DATABASE_URL 不能为空")
        return

    parsed = urlparse(database_url)
    if database_url.startswith("sqlite"):
        _add_item(result, "DATABASE_URL", "ok", "SQLite DATABASE_URL 格式可用")
        return
    if parsed.scheme and parsed.netloc:
        _add_item(result, "DATABASE_URL", "ok", "DATABASE_URL 格式可用")
        return
    _add_item(result, "DATABASE_URL", "error", "DATABASE_URL 格式无效")


def _missing_kdocs_settings(settings: Settings) -> list[str]:
    if settings.kdocs_transport == "mcp":
        return [
            name
            for name, value in {
                "KDOCS_MCP_URL": settings.kdocs_mcp_url,
                "KDOCS_MCP_CLIENT_ID": settings.kdocs_mcp_client_id,
                "KDOCS_ACCESS_TOKEN": settings.kdocs_access_token,
                "KDOCS_DRIVE_ID": settings.kdocs_drive_id,
                "KDOCS_ENFORCEMENT_FILE_ID": settings.kdocs_enforcement_file_id,
                "KDOCS_COURT_TIME_FILE_ID": settings.kdocs_court_time_file_id,
            }.items()
            if not value
        ]
    return [
        name
        for name, value in {
            "KDOCS_BASE_URL": settings.kdocs_base_url,
            "KDOCS_ACCESS_TOKEN": settings.kdocs_access_token,
            "KDOCS_SPACE_ID": settings.kdocs_space_id,
        }.items()
        if not value
    ]


def _missing_wecom_archive_sdk_settings(settings: Settings) -> list[str]:
    if settings.wecom_archive_sidecar_mock:
        return [
            name
            for name, value in {
                "WECOM_ARCHIVE_SIDECAR_URL": settings.wecom_archive_sidecar_url,
            }.items()
            if not value
        ]
    return [
        name
        for name, value in {
            "WECOM_CORP_ID": settings.wecom_corp_id,
            "WECOM_ARCHIVE_SECRET": settings.wecom_archive_secret,
            "WECOM_ARCHIVE_PRIVATE_KEY_PATH": settings.wecom_archive_private_key_path,
            "WECOM_ARCHIVE_PUBLIC_KEY_VER": settings.wecom_archive_public_key_ver,
            "WECOM_ARCHIVE_SIDECAR_URL": settings.wecom_archive_sidecar_url,
        }.items()
        if not value
    ]


def _missing_wecomapi_settings(settings: Settings) -> list[str]:
    return [
        name
        for name, value in {
            "WECOMAPI_BASE_URL": settings.wecomapi_base_url,
            "WECOMAPI_TOKEN": settings.wecomapi_token,
            "WECOMAPI_GUID": settings.wecomapi_guid,
        }.items()
        if not value
    ]


def _missing_wecom_bot_settings(settings: Settings) -> list[str]:
    return [
        name
        for name, value in {
            "WECOM_BOT_SIDECAR_URL": settings.wecom_bot_sidecar_url,
            "WECOM_BOT_SIDECAR_TOKEN": settings.wecom_bot_sidecar_token,
        }.items()
        if not value
    ]


def _validate_wecom_archive_sidecar_url(settings: Settings, result: dict[str, Any], item_name: str) -> bool:
    if urlparse(settings.wecom_archive_sidecar_url or "").scheme not in {"http", "https"}:
        _add_item(result, item_name, "error", "WECOM_ARCHIVE_SIDECAR_URL 必须是 http 或 https URL")
        return False
    return True


def validate_runtime_config(settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "errors": [], "warnings": [], "items": []}

    if settings.wecom_send_mode == "mock":
        _add_item(result, "WECOM_SEND_MODE", "ok", "企业微信发送为 mock 模式")
    elif settings.wecom_send_mode == "webhook" and settings.wecom_webhook_url:
        _add_item(result, "WECOM_SEND_MODE", "ok", "企业微信发送为 webhook 模式，Webhook URL 已配置")
    elif settings.wecom_send_mode == "webhook":
        _add_item(result, "WECOM_SEND_MODE", "error", "WECOM_SEND_MODE=webhook 时必须配置 WECOM_WEBHOOK_URL")
    elif settings.wecom_send_mode == "wecom_cli":
        config_dir = Path(settings.wecom_cli_config_dir).expanduser()
        if not shutil.which(settings.wecom_cli_binary):
            _add_item(
                result,
                "WECOM_SEND_MODE",
                "error",
                f"未找到官方企业微信 CLI：{settings.wecom_cli_binary}，请先安装 @wecom/cli",
            )
        elif not (config_dir / "bot.enc").is_file() or not (config_dir / "mcp_config.enc").is_file():
            _add_item(
                result,
                "WECOM_SEND_MODE",
                "error",
                f"官方企业微信 CLI 尚未初始化，请使用 WECOM_CLI_CONFIG_DIR={config_dir} 执行 wecom-cli init",
            )
        else:
            _add_item(
                result,
                "WECOM_SEND_MODE",
                "warning",
                "官方企业微信 CLI 已安装并初始化；消息能力由企业规模和官方授权动态决定，启用前须执行 wecom-cli msg --help 验证",
            )
    elif settings.wecom_send_mode == "wecom_bot":
        missing = _missing_wecom_bot_settings(settings)
        parsed_url = urlparse(settings.wecom_bot_sidecar_url or "")
        if missing:
            _add_item(
                result,
                "WECOM_SEND_MODE",
                "error",
                f"WECOM_SEND_MODE=wecom_bot 时缺少配置：{', '.join(missing)}",
            )
        elif parsed_url.scheme not in {"http", "https"}:
            _add_item(result, "WECOM_SEND_MODE", "error", "WECOM_BOT_SIDECAR_URL 必须是 http 或 https URL")
        elif parsed_url.scheme == "http" and parsed_url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            _add_item(result, "WECOM_SEND_MODE", "warning", "官方机器人 sidecar 使用远程 HTTP，建议改为 HTTPS 或仅监听本机")
        else:
            _add_item(result, "WECOM_SEND_MODE", "ok", "企业微信发送使用官方智能机器人 WebSocket sidecar")
    else:
        missing = _missing_wecomapi_settings(settings)
        if missing:
            _add_item(result, "WECOM_SEND_MODE", "error", f"WECOM_SEND_MODE=wecomapi 时缺少配置：{', '.join(missing)}")
        elif urlparse(settings.wecomapi_base_url or "").scheme not in {"http", "https"}:
            _add_item(result, "WECOM_SEND_MODE", "error", "WECOMAPI_BASE_URL 必须是 http 或 https URL")
        elif urlparse(settings.wecomapi_base_url or "").scheme == "http":
            _add_item(result, "WECOM_SEND_MODE", "warning", "兼容发送网关已配置但使用 HTTP，生产环境应使用 HTTPS 或私有内网")
        else:
            _add_item(result, "WECOM_SEND_MODE", "warning", "企业微信发送使用非官方兼容网关，可连接自托管 Android RPA；已启用限速、上限和熔断")

    if settings.tencent_doc_mode == "mock":
        _add_item(result, "TENCENT_DOC_MODE", "ok", "腾讯文档为 mock 模式")
    elif settings.tencent_doc_access_token and settings.tencent_doc_sheet_id:
        _add_item(result, "TENCENT_DOC_MODE", "ok", "腾讯文档 real 模式必要配置已提供")
    else:
        _add_item(result, "TENCENT_DOC_MODE", "error", "TENCENT_DOC_MODE=real 时必须配置 TENCENT_DOC_ACCESS_TOKEN 和 TENCENT_DOC_SHEET_ID")

    if settings.kdocs_mode == "mock":
        _add_item(result, "KDOCS_MODE", "ok", "金山文档为 mock 模式")
    else:
        missing = _missing_kdocs_settings(settings)
        if missing:
            _add_item(result, "KDOCS_MODE", "error", f"KDOCS_MODE=real 时缺少配置：{', '.join(missing)}")
        elif settings.kdocs_transport == "gateway" and urlparse(settings.kdocs_base_url or "").scheme not in {"http", "https"}:
            _add_item(result, "KDOCS_MODE", "error", "KDOCS_BASE_URL 必须是 http 或 https URL")
        elif settings.kdocs_transport == "mcp" and urlparse(settings.kdocs_mcp_url or "").scheme != "https":
            _add_item(result, "KDOCS_MODE", "error", "KDOCS_MCP_URL 必须是 https URL")
        else:
            _add_item(result, "KDOCS_MODE", "ok", f"金山文档 real/{settings.kdocs_transport} 模式必要配置已提供")
            if settings.kdocs_transport == "mcp" and not settings.kdocs_payment_file_id:
                _add_item(result, "KDOCS_PAYMENT_FILE_ID", "warning", "缴费登记表尚未配置，缴费同步会明确失败并保留重试日志")

    if settings.ocr_provider == "mock":
        _add_item(result, "OCR_PROVIDER", "ok", "OCR 为 mock 模式")
    elif settings.ocr_provider == "local_text":
        _add_item(result, "OCR_PROVIDER", "warning", "OCR_PROVIDER=local_text 仅适合本地调试")
    elif settings.ocr_provider in {"tencent", "aliyun"}:
        if not settings.ocr_sidecar_url:
            _add_item(result, "OCR_PROVIDER", "error", f"OCR_PROVIDER={settings.ocr_provider} 时必须配置 OCR_SIDECAR_URL")
        elif urlparse(settings.ocr_sidecar_url or "").scheme not in {"http", "https"}:
            _add_item(result, "OCR_PROVIDER", "error", "OCR_SIDECAR_URL 必须是 http 或 https URL")
        else:
            _add_item(result, "OCR_PROVIDER", "ok", f"OCR_PROVIDER={settings.ocr_provider} 将通过 OCR sidecar 识别")

    if settings.legal_extraction_mode == "regex":
        _add_item(result, "LEGAL_EXTRACTION_MODE", "ok", "法律文书字段使用正则抽取；复杂版式可切换 LLM")
    elif not settings.legal_llm_base_url or not settings.legal_llm_model:
        _add_item(result, "LEGAL_EXTRACTION_MODE", "error", "LEGAL_EXTRACTION_MODE=llm 时必须配置 LEGAL_LLM_BASE_URL 和 LEGAL_LLM_MODEL")
    elif urlparse(settings.legal_llm_base_url).scheme not in {"http", "https"}:
        _add_item(result, "LEGAL_EXTRACTION_MODE", "error", "LEGAL_LLM_BASE_URL 必须是 http 或 https URL")
    elif not settings.legal_llm_api_key:
        _add_item(result, "LEGAL_EXTRACTION_MODE", "warning", "LLM 抽取已启用但未配置 API Key，仅适用于无需鉴权的内网模型网关")
    else:
        _add_item(result, "LEGAL_EXTRACTION_MODE", "ok", "腾讯 OCR 文本将通过 LLM 结构化抽取，失败时按配置回退正则")

    if settings.wecom_archive_mode == "mock":
        _add_item(result, "WECOM_ARCHIVE_MODE", "ok", "企业微信会话内容存档为 mock 模式")
    else:
        missing = _missing_wecom_archive_sdk_settings(settings)
        if missing:
            _add_item(result, "WECOM_ARCHIVE_MODE", "error", f"WECOM_ARCHIVE_MODE=real 时缺少配置：{', '.join(missing)}")
        elif not _validate_wecom_archive_sidecar_url(settings, result, "WECOM_ARCHIVE_MODE"):
            pass
        elif settings.wecom_archive_sidecar_mock:
            _add_item(result, "WECOM_ARCHIVE_MODE", "warning", "企业微信会话内容存档使用 sidecar mock，允许缺少真实 Secret/私钥，仅适合本地验收")
        else:
            _add_item(result, "WECOM_ARCHIVE_MODE", "ok", "企业微信会话内容存档 real 模式必要配置已提供，将通过 SDK sidecar 拉取")

    if settings.media_download_mode == "mock":
        _add_item(result, "MEDIA_DOWNLOAD_MODE", "ok", "企业微信媒体下载为 mock 模式")
    else:
        missing = _missing_wecom_archive_sdk_settings(settings)
        if missing:
            _add_item(result, "MEDIA_DOWNLOAD_MODE", "error", f"MEDIA_DOWNLOAD_MODE=real 时缺少配置：{', '.join(missing)}")
        elif not _validate_wecom_archive_sidecar_url(settings, result, "MEDIA_DOWNLOAD_MODE"):
            pass
        elif settings.wecom_archive_sidecar_mock:
            _add_item(result, "MEDIA_DOWNLOAD_MODE", "warning", "企业微信媒体下载使用 sidecar mock，允许缺少真实 Secret/私钥，仅适合本地验收")
        else:
            _add_item(result, "MEDIA_DOWNLOAD_MODE", "ok", "企业微信媒体下载 real 模式必要配置已提供，将通过 SDK sidecar 下载")

    _validate_media_storage(settings, result)
    _validate_backup_storage(settings, result)

    if settings.ops_webhook_url and urlparse(settings.ops_webhook_url).scheme not in {"http", "https"}:
        _add_item(result, "OPS_WEBHOOK_URL", "error", "OPS_WEBHOOK_URL 必须是 http 或 https URL")
    elif settings.ops_webhook_url:
        _add_item(result, "OPS_WEBHOOK_URL", "ok", "系统告警 Webhook 已配置")
    else:
        _add_item(result, "OPS_WEBHOOK_URL", "warning", "系统告警仅在管理后台展示，未配置外部 Webhook")

    if settings.db_auto_create:
        _add_item(result, "DB_AUTO_CREATE", "warning", "DB_AUTO_CREATE=true 适合本地开发，不推荐生产环境")
    else:
        _add_item(result, "DB_AUTO_CREATE", "ok", "DB_AUTO_CREATE=false，生产环境建议使用 Alembic 迁移")

    _validate_database_url(settings, result)

    if settings.auth_enabled and not settings.admin_api_key_list:
        _add_item(result, "AUTH_ENABLED", "error", "AUTH_ENABLED=true 时必须配置 ADMIN_API_KEYS")
    elif settings.auth_enabled:
        _add_item(result, "AUTH_ENABLED", "ok", "API Key 鉴权已开启")
    else:
        _add_item(result, "AUTH_ENABLED", "warning", "AUTH_ENABLED=false，当前鉴权关闭，仅适合本地开发")

    if settings.auth_enabled and not settings.rbac_enabled:
        _add_item(result, "RBAC_ENABLED", "warning", "AUTH_ENABLED=true 但 RBAC_ENABLED=false，将只校验 API Key 不校验角色权限")
    elif settings.rbac_enabled:
        _add_item(result, "RBAC_ENABLED", "ok", "RBAC 权限控制已开启")

    if settings.resource_scope_enabled and not settings.rbac_enabled:
        _add_item(result, "RESOURCE_SCOPE_ENABLED", "warning", "RESOURCE_SCOPE_ENABLED=true 但 RBAC_ENABLED=false，资源权限不会生效")
    elif settings.resource_scope_enabled:
        _add_item(result, "RESOURCE_SCOPE_ENABLED", "ok", "资源级权限控制已开启")

    if settings.tenant_enabled and not settings.resource_scope_enabled:
        _add_item(result, "TENANT_ENABLED", "warning", "TENANT_ENABLED=true 但 RESOURCE_SCOPE_ENABLED=false，租户访问控制不会生效")
    elif settings.tenant_enabled:
        _add_item(result, "TENANT_ENABLED", "ok", "多租户访问控制已开启")
    if settings.tenant_enabled and not settings.auth_enabled:
        _add_item(result, "TENANT_ENABLED", "warning", "AUTH_ENABLED=false，租户访问控制不会生效")

    if settings.tenant_settings_enabled and not settings.tenant_enabled:
        _add_item(result, "TENANT_SETTINGS_ENABLED", "warning", "TENANT_SETTINGS_ENABLED=true 但 TENANT_ENABLED=false，租户级配置不会生效")
    elif settings.tenant_settings_enabled:
        _add_item(result, "TENANT_SETTINGS_ENABLED", "ok", "租户级配置覆盖已开启")
    if settings.tenant_settings_enabled and not settings.tenant_secret_encryption_key:
        _add_item(result, "TENANT_SECRET_ENCRYPTION_KEY", "warning", "TENANT_SECRET_ENCRYPTION_KEY 为空；当前仅做简单存储和脱敏返回，生产建议接入 KMS 或密钥管理")

    if settings.default_api_key_role not in ROLES:
        _add_item(result, "DEFAULT_API_KEY_ROLE", "error", "DEFAULT_API_KEY_ROLE 必须是 admin/legal/auditor/system 之一")
    else:
        _add_item(result, "DEFAULT_API_KEY_ROLE", "ok", f"环境变量 API Key 默认角色为 {settings.default_api_key_role}")

    short_keys = [key for key in settings.admin_api_key_list if len(key) < 8]
    if short_keys:
        _add_item(result, "ADMIN_API_KEYS", "warning", "ADMIN_API_KEYS 中存在长度小于 8 的 key，建议使用更长密钥")
    elif settings.admin_api_key_list:
        _add_item(result, "ADMIN_API_KEYS", "warning", "ADMIN_API_KEYS 已配置；生产环境建议使用数据库 API Key 管理并逐步轮换")

    result["ok"] = not result["errors"]
    return result
