from typing import Any

from app.adapters.ocr_providers.base import success_result


class MockOCRProvider:
    provider_name = "mock"

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        return success_result(
            provider=self.provider_name,
            raw_text="",
            confidence=0,
            metadata={"media_type": media_type, "local_path": local_path, "mock": True},
        )
