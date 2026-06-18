from typing import Any

from app.adapters.ocr_providers.base import failure_result


class AliyunOCRProvider:
    provider_name = "aliyun"

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        return failure_result(
            provider=self.provider_name,
            error="阿里云 OCR Provider 暂未实现",
            metadata={"media_type": media_type, "local_path": local_path},
        )
