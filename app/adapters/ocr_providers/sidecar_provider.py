import base64
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.adapters.ocr_providers.base import failure_result, success_result
from app.core.config import get_settings


class SidecarOCRProvider:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self.settings = get_settings()

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        if not self.settings.ocr_sidecar_url:
            return failure_result(
                provider=self.provider_name,
                error=f"OCR_PROVIDER={self.provider_name} 时必须配置 OCR_SIDECAR_URL",
                metadata={"media_type": media_type, "local_path": local_path},
            )

        path = Path(local_path)
        try:
            content_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
            endpoint = urljoin(self.settings.ocr_sidecar_url.rstrip("/") + "/", "ocr/extract")
            payload = {
                "provider": self.provider_name,
                "media_type": media_type,
                "filename": path.name,
                "content_base64": content_base64,
            }
            response = httpx.post(endpoint, json=payload, timeout=self.settings.wecom_archive_timeout_seconds)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return failure_result(
                provider=self.provider_name,
                error=str(exc),
                metadata={"media_type": media_type, "local_path": local_path},
            )

        if not isinstance(data, dict):
            return failure_result(
                provider=self.provider_name,
                error="OCR sidecar 响应格式错误",
                metadata={"media_type": media_type, "local_path": local_path},
            )
        if data.get("success") is False:
            return failure_result(
                provider=self.provider_name,
                error=str(data.get("error") or "OCR sidecar 识别失败"),
                metadata={**(data.get("metadata") or {}), "media_type": media_type, "local_path": local_path},
            )
        raw_text = str(data.get("raw_text") or data.get("text") or "")
        return success_result(
            provider=str(data.get("provider") or self.provider_name),
            raw_text=raw_text[: self.settings.ocr_max_text_length],
            confidence=float(data.get("confidence") or 0),
            metadata={
                **(data.get("metadata") or {}),
                "media_type": media_type,
                "local_path": local_path,
                "truncated": len(raw_text) > self.settings.ocr_max_text_length,
            },
        )
