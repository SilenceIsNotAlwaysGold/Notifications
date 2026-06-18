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


def _missing_wecom_archive_sdk_settings(settings: Settings) -> list[str]:
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


def _validate_wecom_archive_sidecar_url(settings: Settings, result: dict[str, Any], item_name: str) -> bool:
    if urlparse(settings.wecom_archive_sidecar_url or "").scheme not in {"http", "https"}:
        _add_item(result, item_name, "error", "WECOM_ARCHIVE_SIDECAR_URL 必须是 http 或 https URL")
        return False
    return True


def validate_runtime_config(settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "errors": [], "warnings": [], "items": []}

    if settings.wecom_send_mode == "mock":
        _add_item(result, "WECOM_SEND_MODE", "ok", "企业微信发送为 mock 模式")
    elif settings.wecom_webhook_url:
        _add_item(result, "WECOM_SEND_MODE", "ok", "企业微信发送为 webhook 模式，Webhook URL 已配置")
    else:
        _add_item(result, "WECOM_SEND_MODE", "error", "WECOM_SEND_MODE=webhook 时必须配置 WECOM_WEBHOOK_URL")

    if settings.tencent_doc_mode == "mock":
        _add_item(result, "TENCENT_DOC_MODE", "ok", "腾讯文档为 mock 模式")
    elif settings.tencent_doc_access_token and settings.tencent_doc_sheet_id:
        _add_item(result, "TENCENT_DOC_MODE", "ok", "腾讯文档 real 模式必要配置已提供")
    else:
        _add_item(result, "TENCENT_DOC_MODE", "error", "TENCENT_DOC_MODE=real 时必须配置 TENCENT_DOC_ACCESS_TOKEN 和 TENCENT_DOC_SHEET_ID")

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

    if settings.wecom_archive_mode == "mock":
        _add_item(result, "WECOM_ARCHIVE_MODE", "ok", "企业微信会话内容存档为 mock 模式")
    else:
        missing = _missing_wecom_archive_sdk_settings(settings)
        if missing:
            _add_item(result, "WECOM_ARCHIVE_MODE", "error", f"WECOM_ARCHIVE_MODE=real 时缺少配置：{', '.join(missing)}")
        elif not _validate_wecom_archive_sidecar_url(settings, result, "WECOM_ARCHIVE_MODE"):
            pass
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
        else:
            _add_item(result, "MEDIA_DOWNLOAD_MODE", "ok", "企业微信媒体下载 real 模式必要配置已提供，将通过 SDK sidecar 下载")

    _validate_media_storage(settings, result)

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
