from typing import Any

from app.adapters.ocr_providers.base import failure_result


class TencentOCRProvider:
    provider_name = "tencent"

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        return failure_result(
            provider=self.provider_name,
            error="腾讯云 OCR Provider 暂未实现",
            metadata={"media_type": media_type, "local_path": local_path},
        )
