import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings, get_settings
from app.schemas.recognition_settings import (
    RecognitionCheckOut,
    RecognitionServiceStatus,
    RecognitionSettingsOut,
    RecognitionSettingsUpdate,
)


DEFAULT_ENV_FILE = Path(".env")


class RecognitionSettingsService:
    def __init__(self, settings: Settings | None = None, env_file: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.env_file = env_file or DEFAULT_ENV_FILE

    def current(self) -> RecognitionSettingsOut:
        local_ocr_credentials = bool(self.settings.tencent_ocr_secret_id and self.settings.tencent_ocr_secret_key)
        runtime_ocr_configured = local_ocr_credentials
        if self.settings.ocr_provider == "tencent" and not runtime_ocr_configured:
            runtime_ocr_configured = self._check_ocr().configured
        return RecognitionSettingsOut(
            ocr_provider=self.settings.ocr_provider,
            ocr_sidecar_url=self.settings.ocr_sidecar_url,
            has_tencent_secret_id=bool(self.settings.tencent_ocr_secret_id) or runtime_ocr_configured,
            has_tencent_secret_key=bool(self.settings.tencent_ocr_secret_key) or runtime_ocr_configured,
            secret_mask=self.settings.secret_value_mask,
            tencent_region=self.settings.tencent_ocr_region,
            tencent_pdf_max_pages=self.settings.tencent_ocr_pdf_max_pages,
            extraction_mode=self.settings.legal_extraction_mode,
            llm_base_url=self.settings.legal_llm_base_url,
            has_llm_api_key=bool(self.settings.legal_llm_api_key),
            llm_model=self.settings.legal_llm_model,
            llm_timeout_seconds=self.settings.legal_llm_timeout_seconds,
            llm_max_text_length=self.settings.legal_llm_max_text_length,
            llm_min_confidence=self.settings.legal_llm_min_confidence,
            llm_fallback_to_regex=self.settings.legal_llm_fallback_to_regex,
            data_retention_enabled=self.settings.legal_data_retention_enabled,
            data_retention_days=self.settings.legal_data_retention_days,
            data_retention_review_statuses=self.settings.legal_data_retention_status_list,
        )

    def update(self, payload: RecognitionSettingsUpdate) -> None:
        updates = self._payload_to_env(payload)
        if not updates:
            return
        self._write_env(updates)
        os.environ.update(updates)
        get_settings.cache_clear()
        self.settings = get_settings()

    def check(self) -> RecognitionCheckOut:
        return RecognitionCheckOut(ocr=self._check_ocr(), llm=self._check_llm())

    def _check_ocr(self) -> RecognitionServiceStatus:
        endpoint = urljoin((self.settings.ocr_sidecar_url or "").rstrip("/") + "/", "health")
        if self.settings.ocr_provider in {"mock", "local_text"}:
            return RecognitionServiceStatus(
                configured=True,
                available=True,
                message=f"当前使用 {self.settings.ocr_provider}，不调用云 OCR",
            )
        if not self.settings.ocr_sidecar_url:
            return RecognitionServiceStatus(configured=False, available=False, message="未配置 OCR Sidecar 地址")
        try:
            response = httpx.get(endpoint, timeout=min(self.settings.tencent_ocr_timeout_seconds, 10))
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return RecognitionServiceStatus(
                configured=True,
                available=False,
                message=f"OCR 服务连接失败：{type(exc).__name__}",
                endpoint=endpoint,
            )
        configured = bool(data.get("configured"))
        return RecognitionServiceStatus(
            configured=configured,
            available=data.get("status") == "ok" and configured,
            message="腾讯 OCR 服务可用" if configured else "OCR Sidecar 在线，但腾讯云密钥未生效",
            endpoint=endpoint,
        )

    def _check_llm(self) -> RecognitionServiceStatus:
        base_url = (self.settings.legal_llm_base_url or "").strip()
        model = (self.settings.legal_llm_model or "").strip()
        api_key = (self.settings.legal_llm_api_key or "").strip()
        endpoint = urljoin(base_url.rstrip("/") + "/", "chat/completions") if base_url else None
        if self.settings.legal_extraction_mode != "llm":
            return RecognitionServiceStatus(
                configured=bool(base_url and model),
                available=False,
                message="当前使用规则抽取，AI 结构化未启用",
                endpoint=endpoint,
            )
        if not base_url or not model or not api_key:
            return RecognitionServiceStatus(
                configured=False,
                available=False,
                message="AI 配置不完整，需要接口地址、模型名称和 API Key",
                endpoint=endpoint,
            )
        try:
            response = httpx.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "temperature": 0,
                    "max_tokens": 8,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "只输出 JSON。"},
                        {"role": "user", "content": '输出 {"ok":true}'},
                    ],
                },
                timeout=self.settings.legal_llm_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                raise ValueError("empty response")
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            return RecognitionServiceStatus(
                configured=True,
                available=False,
                message=f"AI 模型连接失败：{type(exc).__name__}",
                endpoint=endpoint,
            )
        return RecognitionServiceStatus(
            configured=True,
            available=True,
            message=f"AI 模型 {model} 可用",
            endpoint=endpoint,
        )

    @staticmethod
    def _payload_to_env(payload: RecognitionSettingsUpdate) -> dict[str, str]:
        mapping = {
            "ocr_provider": "OCR_PROVIDER",
            "ocr_sidecar_url": "OCR_SIDECAR_URL",
            "tencent_pdf_max_pages": "TENCENT_OCR_PDF_MAX_PAGES",
            "extraction_mode": "LEGAL_EXTRACTION_MODE",
            "llm_base_url": "LEGAL_LLM_BASE_URL",
            "llm_api_key": "LEGAL_LLM_API_KEY",
            "llm_model": "LEGAL_LLM_MODEL",
            "llm_timeout_seconds": "LEGAL_LLM_TIMEOUT_SECONDS",
            "llm_max_text_length": "LEGAL_LLM_MAX_TEXT_LENGTH",
            "llm_min_confidence": "LEGAL_LLM_MIN_CONFIDENCE",
            "llm_fallback_to_regex": "LEGAL_LLM_FALLBACK_TO_REGEX",
            "data_retention_enabled": "LEGAL_DATA_RETENTION_ENABLED",
            "data_retention_days": "LEGAL_DATA_RETENTION_DAYS",
            "data_retention_review_statuses": "LEGAL_DATA_RETENTION_REVIEW_STATUSES",
        }
        updates: dict[str, str] = {}
        for field, env_key in mapping.items():
            if field not in payload.model_fields_set:
                continue
            value: Any = getattr(payload, field)
            if isinstance(value, bool):
                updates[env_key] = str(value).lower()
            elif isinstance(value, list):
                updates[env_key] = ",".join(value)
            else:
                updates[env_key] = "" if value is None else str(value).strip()
        return updates

    def _write_env(self, updates: dict[str, str]) -> None:
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = self.env_file.read_text(encoding="utf-8").splitlines() if self.env_file.exists() else []
        seen: set[str] = set()
        next_lines: list[str] = []
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                next_lines.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in updates:
                next_lines.append(f"{key}={self._format_env_value(updates[key])}")
                seen.add(key)
            else:
                next_lines.append(line)
        for key, value in updates.items():
            if key not in seen:
                next_lines.append(f"{key}={self._format_env_value(value)}")
        if self.env_file.exists():
            backup = self.env_file.with_name(f"{self.env_file.name}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            shutil.copy2(self.env_file, backup)
        self.env_file.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")

    @staticmethod
    def _format_env_value(value: str) -> str:
        if value == "":
            return ""
        if any(character.isspace() or character in {'"', "'", "#"} for character in value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value
