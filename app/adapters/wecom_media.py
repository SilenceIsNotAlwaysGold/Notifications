from pathlib import Path
from typing import Any

from app.core.config import get_settings


class WeComMediaAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def download_media(self, raw_message: dict[str, Any], target_path: str) -> dict[str, Any]:
        if self.settings.media_download_mode != "mock":
            return {
                "success": False,
                "local_path": None,
                "file_size": None,
                "error": "真实企业微信媒体下载暂未实现",
            }

        content = self._mock_content(raw_message)
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
