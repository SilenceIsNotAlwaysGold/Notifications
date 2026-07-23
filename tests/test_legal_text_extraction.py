import json as jsonlib

import httpx
import pytest

from app.adapters.legal_llm import LegalLLMAdapter, LegalLLMError
from app.core.config import Settings, get_settings
from app.services.ocr_service import OCRService
from app.services.legal_text_extraction_service import LegalTextExtractionService


class StubLLMAdapter:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or {}
        self.error = error

    def extract(self, text, regex_hints, context_messages=None):
        if self.error:
            raise self.error
        self.context_messages = context_messages or []
        return self.result


def llm_settings(**overrides):
    values = {
        "LEGAL_EXTRACTION_MODE": "llm",
        "LEGAL_LLM_BASE_URL": "https://llm.example.test/v1",
        "LEGAL_LLM_API_KEY": "test-key",
        "LEGAL_LLM_MODEL": "legal-extractor-test",
        "LEGAL_LLM_MIN_CONFIDENCE": 0.75,
        "LEGAL_LLM_FALLBACK_TO_REGEX": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_llm_extractor_fills_fields_from_complex_ocr_layout():
    adapter = StubLLMAdapter(
        {
            "event_type": "judgment",
            "document_type": "民事判决书",
            "case_no": "（2026） 黔 0281 民初 3118 号",
            "plaintiff": "李四",
            "defendant": "张三",
            "court_time": None,
            "amount": None,
            "confidence": 0.96,
            "requires_review": False,
            "review_reasons": [],
            "_response_metadata": {"model": "legal-extractor-test", "finish_reason": "stop"},
        }
    )
    service = LegalTextExtractionService(llm_settings(), adapter)

    result = service.extract("民事判决书\n案 号 （2026） 黔 0281 民初 3118 号\n原 告\n李四\n被 告\n张三")

    assert result["event_type"] == "judgment"
    assert result["document_type"] == "判决书"
    assert result["case_no"] == "（2026）黔0281民初3118号"
    assert result["plaintiff"] == "李四"
    assert result["defendant"] == "张三"
    assert result["extraction_confidence"] == 0.96
    assert result["requires_review"] is False
    assert result["metadata"]["parser"] == "llm_v1"
    assert result["metadata"]["regex_parser"] == "regex_v2"


def test_llm_low_confidence_marks_result_for_review():
    adapter = StubLLMAdapter(
        {
            "event_type": "payment_notice",
            "document_type": None,
            "case_no": None,
            "plaintiff": None,
            "defendant": None,
            "court_time": None,
            "amount": "400元",
            "confidence": 0.51,
            "requires_review": False,
            "review_reasons": [],
        }
    )
    result = LegalTextExtractionService(llm_settings(), adapter).extract("缴费通知：应缴公告费人民币肆佰元")

    assert str(result["amount"]) == "400.00"
    assert result["requires_review"] is True
    assert "结构化抽取置信度低" in result["review_reasons"]


def test_llm_uses_group_context_to_fill_case_number_missing_from_ocr():
    adapter = StubLLMAdapter(
        {
            "event_type": "payment_notice",
            "document_type": None,
            "case_no": "（2026）黔0281民初9001号",
            "plaintiff": None,
            "defendant": "张三",
            "court_time": None,
            "amount": 400,
            "confidence": 0.92,
            "requires_review": False,
            "review_reasons": [],
            "field_sources": {"case_no": "群聊上文", "amount": "OCR原文"},
        }
    )
    context = [
        {
            "message_id": 10,
            "sender_id": "lawyer_001",
            "msg_type": "text",
            "content": "这是（2026）黔0281民初9001号的缴费材料",
            "received_at": "2026-07-23T10:00:00+08:00",
            "position": "before",
        }
    ]

    result = LegalTextExtractionService(llm_settings(), adapter).extract(
        "诉讼费 400 元，请于七日内缴纳",
        context_messages=context,
    )

    assert result["case_no"] == "（2026）黔0281民初9001号"
    assert adapter.context_messages == context
    assert result["metadata"]["context_used"] is True
    assert result["metadata"]["context_message_count"] == 1
    assert result["metadata"]["field_sources"]["case_no"] == "群聊上文"


def test_llm_failure_falls_back_to_regex_and_requires_review():
    adapter = StubLLMAdapter(error=LegalLLMError("gateway timeout"))
    result = LegalTextExtractionService(llm_settings(), adapter).extract(
        "民事判决书\n案号：（2026）黔0281民初3118号\n原告：李四\n被告：张三"
    )

    assert result["event_type"] == "judgment"
    assert result["document_type"] == "判决书"
    assert result["requires_review"] is True
    assert result["metadata"]["parser"] == "regex_v2"
    assert result["metadata"]["llm_status"] == "fallback"
    assert "LLM 不可用" in result["review_reasons"][0]


def test_llm_failure_can_be_configured_as_hard_failure():
    adapter = StubLLMAdapter(error=LegalLLMError("gateway timeout"))
    service = LegalTextExtractionService(llm_settings(LEGAL_LLM_FALLBACK_TO_REGEX=False), adapter)

    with pytest.raises(LegalLLMError, match="gateway timeout"):
        service.extract("民事判决书")


def test_llm_adapter_calls_openai_compatible_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        request = httpx.Request("POST", url)
        content = {
            "event_type": "court_notice",
            "document_type": "开庭传票",
            "court_time": "2026-08-01T09:30:00+08:00",
            "confidence": 0.93,
            "requires_review": False,
            "review_reasons": [],
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "legal-extractor-test",
                "choices": [{"message": {"content": f"```json\n{jsonlib.dumps(content, ensure_ascii=False)}\n```"}, "finish_reason": "stop"}],
            },
        )

    monkeypatch.setattr("app.adapters.legal_llm.httpx.post", fake_post)
    adapter = LegalLLMAdapter(llm_settings())

    result = adapter.extract("开庭传票", {"event_type": "court_notice"})

    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert result["event_type"] == "court_notice"
    assert result["_response_metadata"]["finish_reason"] == "stop"


def test_ocr_service_keeps_tencent_ocr_and_adds_llm_metadata(monkeypatch, tmp_path):
    image_path = tmp_path / "notice.jpg"
    image_path.write_bytes(b"image")
    monkeypatch.setenv("OCR_PROVIDER", "tencent")
    monkeypatch.setenv("OCR_SIDECAR_URL", "http://127.0.0.1:9002")
    monkeypatch.setenv("LEGAL_EXTRACTION_MODE", "llm")
    monkeypatch.setenv("LEGAL_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("LEGAL_LLM_API_KEY", "test-key")
    monkeypatch.setenv("LEGAL_LLM_MODEL", "legal-extractor-test")
    get_settings.cache_clear()

    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        if url.endswith("/ocr/extract"):
            return httpx.Response(
                200,
                request=request,
                json={"success": True, "raw_text": "开庭传票\n八月一日上午开庭", "confidence": 0.98},
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "legal-extractor-test",
                "choices": [
                    {
                        "message": {
                            "content": jsonlib.dumps(
                                {
                                    "event_type": "court_notice",
                                    "document_type": "开庭传票",
                                    "case_no": None,
                                    "plaintiff": None,
                                    "defendant": None,
                                    "court_time": "2026-08-01T09:30:00+08:00",
                                    "amount": None,
                                    "confidence": 0.94,
                                    "requires_review": False,
                                    "review_reasons": [],
                                },
                                ensure_ascii=False,
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr("app.adapters.ocr_providers.sidecar_provider.httpx.post", fake_post)
    monkeypatch.setattr("app.adapters.legal_llm.httpx.post", fake_post)

    result = OCRService().extract_from_file(str(image_path), "image")

    assert result["success"] is True
    assert result["provider"] == "tencent"
    assert result["confidence"] == 0.98
    assert result["event_type"] == "court_notice"
    assert result["metadata"]["parser"] == "llm_v1"
    assert result["metadata"]["llm_status"] == "success"
    assert result["metadata"]["extraction_confidence"] == 0.94
    get_settings.cache_clear()
