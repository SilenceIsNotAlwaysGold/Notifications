import base64
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings


class WeComMediaAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def download_media(self, raw_message: dict[str, Any], target_path: str) -> dict[str, Any]:
        if self.settings.media_download_mode != "mock":
            return self._download_media_from_sidecar(raw_message, target_path)

        content = self._mock_content(raw_message)
        return self._save_content(content, target_path)

    def _download_media_from_sidecar(self, raw_message: dict[str, Any], target_path: str) -> dict[str, Any]:
        if not self.settings.wecom_archive_sidecar_url:
            return {
                "success": False,
                "local_path": None,
                "file_size": None,
                "error": "MEDIA_DOWNLOAD_MODE=real 时必须配置 WECOM_ARCHIVE_SIDECAR_URL",
            }

        endpoint = urljoin(self.settings.wecom_archive_sidecar_url.rstrip("/") + "/", "media/download")
        payload = {
            "raw_message": raw_message,
            "target_filename": Path(target_path).name,
            "corp_id": self.settings.wecom_corp_id,
            "archive_secret": self.settings.wecom_archive_secret,
            "private_key_path": self.settings.wecom_archive_private_key_path,
            "public_key_ver": self.settings.wecom_archive_public_key_ver,
        }
        try:
            response = httpx.post(endpoint, json=payload, timeout=self.settings.wecom_archive_timeout_seconds)
            response.raise_for_status()
            data = response.json()
            content_base64 = data.get("content_base64") if isinstance(data, dict) else None
            if not content_base64:
                return {
                    "success": False,
                    "local_path": None,
                    "file_size": None,
                    "error": "企业微信媒体 sidecar 响应格式错误：缺少 content_base64",
                }
            content = base64.b64decode(str(content_base64), validate=True)
        except Exception as exc:
            return {
                "success": False,
                "local_path": None,
                "file_size": None,
                "error": str(exc),
            }
        return self._save_content(content, target_path)

    def _save_content(self, content: bytes, target_path: str) -> dict[str, Any]:
        max_bytes = self.settings.media_max_file_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            return {
                "success": False,
                "local_path": None,
                "file_size": None,
                "error": "媒体文件超过大小限制",
            }

        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return {"success": True, "local_path": str(path), "file_size": path.stat().st_size, "error": None}

    @staticmethod
    def _mock_content(raw_message: dict[str, Any]) -> bytes:
        msgtype = raw_message.get("msgtype")
        filename = ((raw_message.get("file") or {}).get("filename") or "").lower()
        if msgtype == "image":
            return b"mock image bytes"
        if msgtype == "file" and filename.endswith(".pdf"):
            return b"%PDF-1.4\n% mock pdf bytes\n"
        return b"mock file bytes"
