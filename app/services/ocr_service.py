from typing import Any

from app.adapters.ocr_providers import AliyunOCRProvider, LocalTextOCRProvider, MockOCRProvider, TencentOCRProvider
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.tenant_settings_service import TenantSettingsService
from app.utils.regex_parser import parse_legal_text

class OCRService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = self._build_provider(self.settings.ocr_provider)

    def extract_from_text(self, text: str | None, tenant_id: str | None = None) -> dict[str, Any]:
        keyword_config = self._keyword_config(tenant_id)
        return parse_legal_text(text, keyword_config=keyword_config)

    def extract_from_image(self, file_url: str | None) -> dict[str, Any]:
        return {
            "case_no": None,
            "amounts": [],
            "amount": None,
            "keywords": [],
            "event_types": [],
            "extracted_text": "",
            "metadata": {"parser": "mock", "mock": True, "file_url": file_url},
        }

    def extract_from_pdf(self, file_url: str | None) -> dict[str, Any]:
        return {
            "case_no": None,
            "amounts": [],
            "amount": None,
            "keywords": [],
            "event_types": [],
            "extracted_text": "",
            "metadata": {"parser": "mock", "mock": True, "file_url": file_url},
        }

    def extract_from_file(self, local_path: str, media_type: str, tenant_id: str | None = None) -> dict[str, Any]:
        effective = self._effective_settings(tenant_id)
        if not effective["feature_flags"].get("enable_ocr", True):
            return {
                "success": False,
                "raw_text": "",
                "case_no": None,
                "amount": None,
                "amounts": [],
                "event_type": "unknown",
                "event_types": [],
                "event_time": None,
                "keywords": [],
                "confidence": 0,
                "provider": effective["ocr"]["provider"],
                "extracted_text": "",
                "metadata": {"tenant_settings_source": effective["source"]},
                "error": "租户已关闭 OCR",
            }
        provider_name = effective["ocr"]["provider"]
        provider = self._build_provider(provider_name)
        try:
            provider_result = provider.extract(local_path, media_type)
        except Exception as exc:
            provider_result = {
                "success": False,
                "raw_text": "",
                "provider": provider_name,
                "confidence": 0,
                "metadata": {"media_type": media_type, "local_path": local_path},
                "error": str(exc),
            }
        raw_text = provider_result.get("raw_text") or ""
        parsed = parse_legal_text(raw_text, keyword_config=effective["keyword_config"])
        metadata = provider_result.get("metadata") or {}
        return {
            "success": bool(provider_result.get("success")),
            "raw_text": raw_text,
            "case_no": parsed.get("case_no"),
            "amount": parsed.get("amount"),
            "amounts": parsed.get("amounts", []),
            "event_type": parsed.get("event_type") or "unknown",
            "event_types": parsed.get("event_types") or [],
            "event_time": parsed.get("event_time"),
            "keywords": parsed.get("keywords", []),
            "confidence": provider_result.get("confidence", 0),
            "provider": provider_result.get("provider") or provider_name,
            "extracted_text": raw_text,
            "metadata": {
                **metadata,
                "provider": provider_result.get("provider") or provider_name,
                "provider_success": bool(provider_result.get("success")),
                "provider_error": provider_result.get("error"),
                "parser": parsed.get("metadata", {}).get("parser"),
                "tenant_settings_source": effective["source"],
                "payment_keyword_conflict": parsed.get("metadata", {}).get("payment_keyword_conflict"),
            },
            "error": provider_result.get("error"),
        }

    @staticmethod
    def _build_provider(provider_name: str):
        if provider_name == "local_text":
            return LocalTextOCRProvider()
        if provider_name == "tencent":
            return TencentOCRProvider()
        if provider_name == "aliyun":
            return AliyunOCRProvider()
        return MockOCRProvider()

    def _effective_settings(self, tenant_id: str | None) -> dict[str, Any]:
        if tenant_id is None:
            return {
                "source": "global",
                "ocr": {
                    "provider": self.settings.ocr_provider,
                    "enable_reprocess": self.settings.ocr_enable_reprocess,
                    "max_text_length": self.settings.ocr_max_text_length,
                },
                "feature_flags": {"enable_ocr": True},
                "keyword_config": {},
            }
        db = SessionLocal()
        try:
            return TenantSettingsService(db).get_effective_settings(tenant_id)
        finally:
            db.close()

    def _keyword_config(self, tenant_id: str | None) -> dict[str, list[str]] | None:
        if tenant_id is None:
            return None
        db = SessionLocal()
        try:
            return TenantSettingsService(db).get_effective_settings(tenant_id).get("keyword_config")
        finally:
            db.close()
