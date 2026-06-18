from pathlib import Path
from typing import Any

from app.adapters.ocr_providers.base import failure_result, success_result
from app.core.config import get_settings


class LocalTextOCRProvider:
    provider_name = "local_text"

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        txt_path = Path(local_path).with_suffix(".txt")
        if not txt_path.exists():
            return failure_result(
                provider=self.provider_name,
                error="未找到同名 OCR 文本文件",
                metadata={"media_type": media_type, "local_path": local_path, "txt_path": str(txt_path)},
            )
        text = txt_path.read_text(encoding="utf-8")
        max_length = get_settings().ocr_max_text_length
        return success_result(
            provider=self.provider_name,
            raw_text=text[:max_length],
            confidence=0.9,
            metadata={
                "media_type": media_type,
                "local_path": local_path,
                "txt_path": str(txt_path),
                "truncated": len(text) > max_length,
            },
        )
