import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.adapters.legal_llm import LegalLLMAdapter, LegalLLMError
from app.core.config import Settings, get_settings
from app.utils.datetime_utils import app_timezone
from app.utils.regex_parser import extract_event_time, parse_legal_text
from app.utils.repayment_annotation import repayment_annotation_from_context

ALLOWED_EVENT_TYPES = {
    "judgment",
    "repayment_agreement",
    "court_notice",
    "payment_notice",
    "payment_screenshot",
    "keyword",
    "unknown",
}
DOCUMENT_TYPE_ALIASES = {
    "判决书": "判决书",
    "民事判决书": "判决书",
    "调解书": "调解书",
    "民事调解书": "调解书",
    "裁定书": "裁定书",
    "民事裁定书": "裁定书",
    "开庭传票": "开庭传票",
    "传票": "开庭传票",
}
EVENT_TYPE_ALIASES = {
    "判决书": "judgment",
    "调解书": "judgment",
    "裁定书": "judgment",
    "开庭传票": "court_notice",
    "传票": "court_notice",
    "缴费通知": "payment_notice",
    "付款截图": "payment_screenshot",
    "支付凭证": "payment_screenshot",
    "还款协议": "repayment_agreement",
    "调解协议": "repayment_agreement",
}

STRUCTURED_FIELDS = {
    "court_name",
    "court_room",
    "hearing_mode",
    "judge_phone",
    "identity_number",
    "document_date",
    "repayment_due_date",
    "enforcement_case_no",
    "order_no",
    "repayment_plan",
    "installment_sequence",
    "payment_type",
    "payment_deadline",
    "payment_term_days",
    "agreement_date",
    "arbitration_institution",
}


class LegalTextExtractionService:
    def __init__(
        self,
        settings: Settings | None = None,
        llm_adapter: LegalLLMAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm_adapter = llm_adapter or LegalLLMAdapter(self.settings)

    def extract(
        self,
        text: str | None,
        keyword_config: dict[str, list[str]] | None = None,
        context_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        regex_result = self._enrich_regex_result(parse_legal_text(text, keyword_config=keyword_config), text or "")
        if self.settings.legal_extraction_mode != "llm" or (not text and not context_messages):
            return self._apply_repayment_annotation(regex_result, context_messages)

        try:
            if context_messages:
                llm_result = self.llm_adapter.extract(text or "", regex_result, context_messages=context_messages)
            else:
                llm_result = self.llm_adapter.extract(text or "", regex_result)
            result = self._merge_and_validate(text or "", regex_result, llm_result, context_messages=context_messages)
            return self._apply_repayment_annotation(result, context_messages)
        except LegalLLMError as exc:
            if not self.settings.legal_llm_fallback_to_regex:
                raise
            return self._apply_repayment_annotation(self._fallback_result(regex_result, str(exc)), context_messages)
        except Exception as exc:
            if not self.settings.legal_llm_fallback_to_regex:
                raise LegalLLMError(f"LLM 抽取处理失败：{type(exc).__name__}") from exc
            fallback = self._fallback_result(regex_result, f"LLM 抽取处理失败：{type(exc).__name__}")
            return self._apply_repayment_annotation(fallback, context_messages)

    @classmethod
    def _enrich_regex_result(cls, result: dict[str, Any], text: str) -> dict[str, Any]:
        metadata = dict(result.get("metadata") or {})
        structured = dict(metadata.get("structured_fields") or {})
        if result.get("event_type") == "payment_notice":
            structured.update(cls._payment_notice_fields(text))
        elif result.get("event_type") == "repayment_agreement":
            structured.update(cls._repayment_agreement_fields(text))
            parties = cls._repayment_agreement_parties(text)
            result = {
                **result,
                "plaintiff": result.get("plaintiff") or parties.get("plaintiff"),
                "defendant": result.get("defendant") or parties.get("defendant"),
                "amount": result.get("amount") or parties.get("amount"),
            }
        else:
            return result
        return {**result, "metadata": {**metadata, "structured_fields": structured}}

    @staticmethod
    def _apply_repayment_annotation(
        result: dict[str, Any],
        context_messages: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        matched = repayment_annotation_from_context(context_messages)
        if not matched:
            return result
        annotation, message = matched
        metadata = dict(result.get("metadata") or {})
        structured_fields = dict(metadata.get("structured_fields") or {})
        if annotation.get("installment_sequence") is not None:
            structured_fields["installment_sequence"] = annotation["installment_sequence"]
        structured_fields["payment_kind"] = annotation.get("payment_kind")
        field_sources = dict(metadata.get("field_sources") or {})
        relative = "前" if message.get("position") == "before" else "后"
        source = f"截图{relative}说明文字#{message.get('message_id')}"
        field_sources.update(
            {
                "plaintiff": source,
                "defendant": source,
                "amount": source,
                "installment_sequence": source,
            }
        )
        amounts = list(result.get("amounts") or [])
        if annotation["amount"] not in amounts:
            amounts.insert(0, annotation["amount"])
        return {
            **result,
            "event_type": "payment_screenshot",
            "event_types": ["payment_screenshot"],
            "plaintiff": annotation["plaintiff"],
            "defendant": annotation["defendant"],
            "amount": annotation["amount"],
            "amounts": amounts,
            "metadata": {
                **metadata,
                "field_sources": field_sources,
                "structured_fields": structured_fields,
                "repayment_annotation": {
                    **annotation,
                    "amount": str(annotation["amount"]),
                    "message_id": message.get("message_id"),
                },
            },
        }

    def _merge_and_validate(
        self,
        text: str,
        regex_result: dict[str, Any],
        llm_result: dict[str, Any],
        context_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        review_reasons = self._review_reasons(llm_result)
        llm_event_type = self._event_type(llm_result.get("event_type"))
        regex_event_type = regex_result["event_type"]
        if llm_event_type in {None, "unknown"} and regex_event_type != "unknown":
            event_type = regex_event_type
        else:
            event_type = llm_event_type or regex_event_type
        document_type = self._document_type(llm_result.get("document_type")) or regex_result.get("document_type")
        case_no = self._case_no(llm_result.get("case_no")) or regex_result.get("case_no")
        plaintiff = self._short_text(llm_result.get("plaintiff")) or regex_result.get("plaintiff")
        defendant = self._short_text(llm_result.get("defendant")) or regex_result.get("defendant")
        if case_no and not regex_result.get("case_no") and not self._has_nonmetadata_evidence(case_no, text, context_messages):
            case_no = None
            review_reasons.append("案号仅来自群历史关联案件，不能作为当前资料归属依据")
        if plaintiff and not regex_result.get("plaintiff") and not self._has_nonmetadata_evidence(plaintiff, text, context_messages):
            plaintiff = None
        if defendant and not regex_result.get("defendant") and not self._has_nonmetadata_evidence(defendant, text, context_messages):
            defendant = None
        court_time = self._datetime(llm_result.get("court_time")) or regex_result.get("court_time")
        amount = self._amount(llm_result.get("amount"))
        if amount is None:
            amount = regex_result.get("amount")
        confidence = self._confidence(llm_result.get("confidence"))
        structured_fields = {
            **(
                self._repayment_agreement_fields(text)
                if event_type == "repayment_agreement"
                else {}
            ),
            **self._structured_fields(llm_result),
        }
        if event_type == "payment_notice":
            structured_fields = {
                **self._payment_notice_fields(text),
                **structured_fields,
            }

        if self._has_classification_conflict(llm_event_type, regex_event_type):
            review_reasons.append("LLM 与规则的材料类型判断不一致")
        if self._has_case_no_conflict(case_no, regex_result.get("case_no")):
            review_reasons.append("LLM 与规则提取的案号不一致")
        review_reasons.extend(
            self._missing_critical_fields(
                event_type=event_type,
                document_type=document_type,
                plaintiff=plaintiff,
                defendant=defendant,
                court_time=court_time,
                amount=amount,
            )
        )
        if event_type == "repayment_agreement" and not (
            structured_fields.get("repayment_plan", {}).get("installments")
            if isinstance(structured_fields.get("repayment_plan"), dict)
            else False
        ):
            review_reasons.append("还款协议缺少可执行的分期计划")
        if confidence < self.settings.legal_llm_min_confidence:
            review_reasons.append("结构化抽取置信度低")

        review_reasons = list(dict.fromkeys(reason for reason in review_reasons if reason))
        response_metadata = llm_result.get("_response_metadata")
        if not isinstance(response_metadata, dict):
            response_metadata = {}
        amounts = list(regex_result.get("amounts") or [])
        if amount is not None and amount not in amounts:
            amounts.insert(0, amount)

        field_sources = llm_result.get("field_sources")
        if not isinstance(field_sources, dict):
            field_sources = {}
        return {
            **regex_result,
            "case_no": case_no,
            "amount": amount,
            "amounts": amounts,
            "document_type": document_type,
            "plaintiff": plaintiff,
            "defendant": defendant,
            "court_time": court_time,
            "requires_review": bool(llm_result.get("requires_review")) or bool(review_reasons),
            "event_type": event_type,
            "event_types": [] if event_type == "unknown" else [event_type],
            "event_time": court_time if event_type == "court_notice" else regex_result.get("event_time"),
            "extracted_text": text,
            "extraction_confidence": confidence,
            "review_reasons": review_reasons,
            "metadata": {
                **(regex_result.get("metadata") or {}),
                "parser": "llm_v1",
                "regex_parser": (regex_result.get("metadata") or {}).get("parser"),
                "llm_status": "success",
                "llm_model": response_metadata.get("model") or self.settings.legal_llm_model,
                "llm_finish_reason": response_metadata.get("finish_reason"),
                "llm_request_hash": response_metadata.get("request_hash"),
                "llm_duration_ms": response_metadata.get("duration_ms"),
                "llm_input_tokens": response_metadata.get("input_tokens"),
                "llm_output_tokens": response_metadata.get("output_tokens"),
                "llm_input_truncated": bool(response_metadata.get("truncated")),
                "context_message_count": len(context_messages or []),
                "context_used": bool(context_messages),
                "field_sources": {
                    str(key)[:50]: str(value)[:100]
                    for key, value in field_sources.items()
                    if value is not None
                },
                "structured_fields": structured_fields,
                "extraction_confidence": confidence,
                "review_reasons": review_reasons,
            },
        }

    @staticmethod
    def _structured_fields(llm_result: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in STRUCTURED_FIELDS:
            value = llm_result.get(key)
            if value in (None, "", [], {}):
                continue
            if key == "repayment_plan":
                if not isinstance(value, dict):
                    continue
                installments = value.get("installments")
                if isinstance(installments, list):
                    value = {
                        **{str(k)[:50]: v for k, v in value.items() if k != "installments" and isinstance(v, (str, int, float, type(None)))},
                        "installments": [
                            {
                                "due_date": str(item.get("due_date") or "")[:10],
                                "amount": item.get("amount"),
                                "sequence": item.get("sequence"),
                            }
                            for item in installments[:120]
                            if isinstance(item, dict) and item.get("due_date")
                        ],
                    }
            elif not isinstance(value, (str, int, float, bool)):
                continue
            result[key] = value
        return result

    @staticmethod
    def _payment_notice_fields(text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        payment_type = re.search(r"(案件受理费|诉讼费|公告费|执行费|保全费|开庭费|鉴定费)", text)
        if payment_type:
            result["payment_type"] = payment_type.group(1)
        absolute = re.search(
            r"(?:请于|须于|应于|截止(?:日期)?(?:为|至)?)[^\d]{0,8}"
            r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?",
            text,
        )
        if absolute:
            try:
                result["payment_deadline"] = date(
                    int(absolute.group(1)),
                    int(absolute.group(2)),
                    int(absolute.group(3)),
                ).isoformat()
            except ValueError:
                pass
        short_absolute = re.search(
            r"(?<!\d)(\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:日)?(?:之前|前|截止)[^。；\n]{0,12}?(?:缴纳|交纳|缴费|交费)",
            text,
        )
        if "payment_deadline" not in result and short_absolute:
            try:
                result["payment_deadline"] = date(
                    2000 + int(short_absolute.group(1)),
                    int(short_absolute.group(2)),
                    int(short_absolute.group(3)),
                ).isoformat()
            except ValueError:
                pass
        relative = re.search(r"(?:收到|送达|接到|本通知)?[^。；\n]{0,20}?(\d{1,3})\s*(?:日|天)内[^。；\n]{0,20}?(?:缴纳|交纳|缴费|交费)", text)
        if not relative:
            relative = re.search(r"(?:缴费|交费|缴纳|交纳)[^。；\n]{0,20}?(\d{1,3})\s*(?:日|天)内", text)
        if relative:
            days = int(relative.group(1))
            if 1 <= days <= 365:
                result["payment_term_days"] = days
        return result

    @staticmethod
    def _repayment_agreement_fields(text: str) -> dict[str, Any]:
        normalized = text or ""
        installments: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        pattern = re.compile(
            r"(?:^|[\n；;])\s*(\d{1,3})\s*[.、]?\s*"
            r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
            r"\s*[:：]?\s*(?:应?还款|支付)\s*([\d,，]+(?:\.\d{1,2})?)\s*元?",
            re.MULTILINE,
        )
        for match in pattern.finditer(normalized):
            try:
                due_date = date(int(match.group(2)), int(match.group(3)), int(match.group(4))).isoformat()
                amount = Decimal(match.group(5).replace(",", "").replace("，", "")).quantize(Decimal("0.01"))
            except (ValueError, InvalidOperation):
                continue
            key = (due_date, str(amount))
            if key in seen:
                continue
            seen.add(key)
            installments.append({"sequence": int(match.group(1)), "due_date": due_date, "amount": amount})

        result: dict[str, Any] = {}
        if installments:
            total_match = re.search(
                r"(?:合计欠|欠款总金额|总欠款)[^\d]{0,20}([\d,，]+(?:\.\d{1,2})?)\s*元",
                normalized,
            )
            total = None
            if total_match:
                try:
                    total = Decimal(total_match.group(1).replace(",", "").replace("，", "")).quantize(Decimal("0.01"))
                except InvalidOperation:
                    total = None
            result["repayment_due_date"] = installments[-1]["due_date"]
            result["repayment_plan"] = {
                "first_payment_date": installments[0]["due_date"],
                "installment_count": len(installments),
                "total_debt": total or sum((item["amount"] for item in installments), Decimal("0.00")),
                "installments": installments,
            }

        institution = re.search(r"提交\s*([\u4e00-\u9fa5]{2,30}仲裁委员会)", normalized)
        if institution:
            result["arbitration_institution"] = institution.group(1)

        signing_dates: list[date] = []
        for match in re.finditer(r"日期\s*[:：]?\s*(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", normalized):
            try:
                signing_dates.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
            except ValueError:
                continue
        if signing_dates:
            result["agreement_date"] = max(signing_dates).isoformat()
        return result

    @staticmethod
    def _repayment_agreement_parties(text: str) -> dict[str, Any]:
        normalized = text or ""
        result: dict[str, Any] = {}
        creditor = re.search(
            r"甲方\s*[（(]?\s*债权人\s*[）)]?\s*[:：]\s*([^\n；;]{2,100})",
            normalized,
        )
        debtor = re.search(
            r"乙方\s*[（(]?\s*债务人\s*[）)]?\s*[:：]\s*([^，,\n；;]{2,50})",
            normalized,
        )
        total = re.search(
            r"(?:合计欠|欠款总金额|总欠款)[^\d]{0,20}([\d,，]+(?:\.\d{1,2})?)\s*元",
            normalized,
        )
        if creditor:
            result["plaintiff"] = creditor.group(1).strip()
        if debtor:
            result["defendant"] = debtor.group(1).strip()
        if total:
            try:
                result["amount"] = Decimal(total.group(1).replace(",", "").replace("，", "")).quantize(Decimal("0.01"))
            except InvalidOperation:
                pass
        return result

    @staticmethod
    def _has_nonmetadata_evidence(
        value: str,
        text: str,
        context_messages: list[dict[str, Any]] | None,
    ) -> bool:
        normalize = lambda content: re.sub(r"[\s()（）,，。·]", "", content or "")
        expected = normalize(value)
        if expected and expected in normalize(text):
            return True
        return any(
            message.get("position") != "metadata" and expected in normalize(str(message.get("content") or ""))
            for message in context_messages or []
        )

    @staticmethod
    def _fallback_result(regex_result: dict[str, Any], reason: str) -> dict[str, Any]:
        existing_reasons = list(regex_result.get("review_reasons") or [])
        review_reasons = list(dict.fromkeys([*existing_reasons, "LLM 不可用，已回退规则抽取"]))
        return {
            **regex_result,
            "requires_review": True,
            "extraction_confidence": None,
            "review_reasons": review_reasons,
            "metadata": {
                **(regex_result.get("metadata") or {}),
                "llm_status": "fallback",
                "llm_error": reason,
                "review_reasons": review_reasons,
            },
        }

    @staticmethod
    def _event_type(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        normalized = EVENT_TYPE_ALIASES.get(normalized, normalized)
        return normalized if normalized in ALLOWED_EVENT_TYPES else None

    @staticmethod
    def _document_type(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        return DOCUMENT_TYPE_ALIASES.get(value.strip())

    @staticmethod
    def _case_no(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = re.sub(r"\s+", "", value.strip()).replace("(", "（").replace(")", "）")
        if not normalized or len(normalized) > 100 or "号" not in normalized:
            return None
        return normalized

    @staticmethod
    def _short_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.strip().split())
        return normalized[:100] or None

    @staticmethod
    def _datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return extract_event_time(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=app_timezone())
        return parsed

    @staticmethod
    def _amount(value: Any) -> Decimal | None:
        if value is None or isinstance(value, bool):
            return None
        normalized = re.sub(r"[¥￥元人民币,，\s]", "", str(value))
        try:
            amount = Decimal(normalized).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None
        return amount if amount > 0 else None

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return min(max(confidence, 0.0), 1.0)

    @staticmethod
    def _review_reasons(llm_result: dict[str, Any]) -> list[str]:
        reasons = llm_result.get("review_reasons")
        if not isinstance(reasons, list):
            return []
        return [str(reason).strip()[:200] for reason in reasons if str(reason).strip()]

    @staticmethod
    def _has_classification_conflict(llm_event_type: str | None, regex_event_type: Any) -> bool:
        return (
            llm_event_type is not None
            and regex_event_type not in {None, "unknown", "keyword"}
            and llm_event_type != regex_event_type
        )

    @staticmethod
    def _has_case_no_conflict(llm_case_no: str | None, regex_case_no: Any) -> bool:
        if not llm_case_no or not regex_case_no:
            return False
        normalize = lambda value: re.sub(r"[\s()（）]", "", str(value))
        return normalize(llm_case_no) != normalize(regex_case_no)

    @staticmethod
    def _missing_critical_fields(
        *,
        event_type: str,
        document_type: str | None,
        plaintiff: str | None,
        defendant: str | None,
        court_time: datetime | None,
        amount: Decimal | None,
    ) -> list[str]:
        missing: list[str] = []
        if event_type == "unknown":
            missing.append("无法判断材料类型")
        elif event_type == "judgment":
            if not document_type:
                missing.append("缺少文书类型")
            if not plaintiff:
                missing.append("缺少原告")
            if not defendant:
                missing.append("缺少被告")
        elif event_type == "court_notice":
            if not court_time:
                missing.append("缺少开庭时间")
            if not defendant:
                missing.append("缺少被告")
        elif event_type in {"payment_notice", "payment_screenshot"} and amount is None:
            missing.append("缺少金额")
        return missing
