from typing import Any, Protocol


class BaseOCRProvider(Protocol):
    provider_name: str

    def extract(self, local_path: str, media_type: str) -> dict[str, Any]:
        ...


def success_result(provider: str, raw_text: str, confidence: float, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": True,
        "raw_text": raw_text,
        "provider": provider,
        "confidence": confidence,
        "metadata": metadata or {},
        "error": None,
    }


def failure_result(provider: str, error: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "raw_text": "",
        "provider": provider,
        "confidence": 0,
        "metadata": metadata or {},
        "error": error,
    }
