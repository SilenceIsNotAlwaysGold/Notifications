import json
import hashlib
import time
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings, get_settings


class LegalLLMError(RuntimeError):
    pass


class LegalLLMAdapter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def extract(
        self,
        text: str,
        regex_hints: dict[str, Any],
        context_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.legal_llm_base_url:
            raise LegalLLMError("未配置 LEGAL_LLM_BASE_URL")
        if not self.settings.legal_llm_model:
            raise LegalLLMError("未配置 LEGAL_LLM_MODEL")

        endpoint = urljoin(self.settings.legal_llm_base_url.rstrip("/") + "/", "chat/completions")
        headers = {"Content-Type": "application/json"}
        if self.settings.legal_llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.legal_llm_api_key}"

        prompt_text = text[: self.settings.legal_llm_max_text_length]
        payload = {
            "model": self.settings.legal_llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是中国法律文书结构化抽取器。只输出 JSON 对象，不得输出解释。"
                        "event_type 只能是 judgment、repayment_agreement、court_notice、payment_notice、"
                        "payment_screenshot、keyword、unknown；document_type 只能是判决书、"
                        "调解书、裁定书、开庭传票或 null。court_time 使用带时区的 ISO 8601；"
                        "amount 使用阿拉伯数字；confidence 是 0 到 1。OCR 文本是判断材料内容的主要依据；"
                        "群聊上下文包含相邻消息、附件 OCR 摘要、群资料和已绑定案件，可用于补充案号、当事人和材料用途，"
                        "若截图后的相邻文字采用‘原告+被告+第几期还款+金额’格式，应将当前材料识别为 payment_screenshot，"
                        "并从该说明文字提取 plaintiff、defendant、amount 和 installment_sequence。"
                        "但不得把明显属于其他案件的信息套用到当前材料。群内存在多个案件时，必须依据明确案号或紧邻对话建立关联。"
                        "信息冲突或无法确认关联时必须 requires_review=true，并在 review_reasons 中说明。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "抽取法律材料字段",
                            "output_schema": {
                                "event_type": "string",
                                "document_type": "string|null",
                                "case_no": "string|null",
                                "plaintiff": "string|null",
                                "defendant": "string|null",
                                "court_time": "string|null",
                                "amount": "number|null",
                                "court_name": "string|null",
                                "court_room": "string|null",
                                "hearing_mode": "线上|现场|待确认|null",
                                "judge_phone": "string|null",
                                "identity_number": "string|null",
                                "document_date": "YYYY-MM-DD|null",
                                "repayment_due_date": "YYYY-MM-DD|null",
                                "enforcement_case_no": "string|null",
                                "order_no": "string|null",
                                "installment_sequence": "number|null",
                                "repayment_plan": {
                                    "first_payment_date": "YYYY-MM-DD|null",
                                    "monthly_payment_day": "number|null",
                                    "installment_count": "number|null",
                                    "installment_amount": "number|null",
                                    "final_installment_amount": "number|null",
                                    "total_debt": "number|null",
                                    "installments": "[{due_date: YYYY-MM-DD, amount: number, sequence: number}]",
                                },
                                "confidence": "number",
                                "requires_review": "boolean",
                                "review_reasons": "string[]",
                                "field_sources": "object",
                            },
                            "regex_hints": self._json_safe_hints(regex_hints),
                            "ocr_text": prompt_text,
                            "group_context": context_messages or [],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }

        started_at = time.monotonic()
        try:
            response = httpx.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self.settings.legal_llm_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LegalLLMError(f"LLM 抽取请求失败：{type(exc).__name__}") from exc

        parsed = self._decode_json_object(content)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        parsed["_response_metadata"] = {
            "model": data.get("model") or self.settings.legal_llm_model,
            "finish_reason": data.get("choices", [{}])[0].get("finish_reason"),
            "truncated": len(text) > self.settings.legal_llm_max_text_length,
            "context_message_count": len(context_messages or []),
            "request_hash": hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "duration_ms": int((time.monotonic() - started_at) * 1000),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        return parsed

    @staticmethod
    def _decode_json_object(content: Any) -> dict[str, Any]:
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        if not isinstance(content, str):
            raise LegalLLMError("LLM 抽取响应不是文本")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```")
            cleaned = cleaned.removesuffix("```").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LegalLLMError("LLM 抽取响应不是有效 JSON") from exc
        if not isinstance(parsed, dict):
            raise LegalLLMError("LLM 抽取响应必须是 JSON 对象")
        return parsed

    @staticmethod
    def _json_safe_hints(regex_hints: dict[str, Any]) -> dict[str, Any]:
        return {
            key: str(value) if key in {"amount", "court_time", "event_time"} and value is not None else value
            for key, value in regex_hints.items()
            if key
            in {
                "event_type",
                "document_type",
                "case_no",
                "plaintiff",
                "defendant",
                "court_time",
                "amount",
            }
        }
