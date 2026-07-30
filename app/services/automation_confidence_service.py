from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.utils.regex_parser import is_payment_done_text


AutomationAction = Literal["write", "remind"]


@dataclass(frozen=True)
class AutomationDecision:
    action: AutomationAction
    outcome: Literal["auto", "review"]
    confidence: float | None
    threshold: float
    reasons: tuple[str, ...]
    confidence_source: str | None

    @property
    def should_auto_execute(self) -> bool:
        return self.outcome == "auto"

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "outcome": self.outcome,
            "confidence": self.confidence,
            "threshold": self.threshold,
            "reasons": list(self.reasons),
            "confidence_source": self.confidence_source,
        }


class AutomationConfidenceService:
    """Decide whether extracted business data can execute without review."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(
        self,
        result: dict[str, Any],
        *,
        action: AutomationAction | None = None,
        allow_rule_confidence: bool = False,
        extra_reasons: list[str] | None = None,
    ) -> AutomationDecision:
        event_type = str(result.get("event_type") or "unknown")
        resolved_action = action or ("remind" if event_type == "payment_notice" else "write")
        threshold = (
            self.settings.legal_auto_remind_min_confidence
            if resolved_action == "remind"
            else self.settings.legal_auto_write_min_confidence
        )
        confidence, source = self._confidence(result, allow_rule_confidence=allow_rule_confidence)
        reasons = self._review_reasons(result)
        reasons.extend(self._missing_critical_fields(result))
        reasons.extend(extra_reasons or [])

        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        if metadata.get("llm_status") == "fallback":
            reasons.append("AI 不可用，规则结果不能自动执行")
        if confidence is None:
            reasons.append("缺少可用于自动执行的结构化置信度")
        elif confidence < threshold:
            reasons.append(f"置信度 {confidence:.0%} 低于自动{self._action_label(resolved_action)}阈值 {threshold:.0%}")

        reasons = list(dict.fromkeys(reason for reason in reasons if reason))
        return AutomationDecision(
            action=resolved_action,
            outcome="review" if reasons else "auto",
            confidence=confidence,
            threshold=threshold,
            reasons=tuple(reasons),
            confidence_source=source,
        )

    @staticmethod
    def apply(result: dict[str, Any], decision: AutomationDecision) -> dict[str, Any]:
        metadata = dict(result.get("metadata") or {})
        metadata["automation_decision"] = decision.as_dict()
        result["metadata"] = metadata
        result["requires_review"] = not decision.should_auto_execute
        result["review_reasons"] = list(decision.reasons)
        return result

    def _confidence(
        self,
        result: dict[str, Any],
        *,
        allow_rule_confidence: bool,
    ) -> tuple[float | None, str | None]:
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        candidates = (
            (result.get("extraction_confidence"), "ai_extraction"),
            (metadata.get("extraction_confidence"), "ai_extraction"),
            (metadata.get("automation_confidence"), "deterministic_rule"),
        )
        for value, source in candidates:
            confidence = self._normalized_confidence(value)
            if confidence is not None:
                return confidence, source
        if allow_rule_confidence:
            confidence = self._rule_confidence(result)
            if confidence is not None:
                return confidence, "deterministic_rule"
        return None, None

    @staticmethod
    def _normalized_confidence(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        return min(max(confidence, 0.0), 1.0)

    @classmethod
    def _rule_confidence(cls, result: dict[str, Any]) -> float | None:
        event_type = result.get("event_type")
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
        if event_type == "payment_notice":
            if metadata.get("payment_keyword_conflict"):
                return None
            score = Decimal("0.35")
            if cls._positive_amount(result.get("amount")):
                score += Decimal("0.25")
            if result.get("defendant") or structured.get("defendant"):
                score += Decimal("0.20")
            if structured.get("payment_type") or cls._payment_type_in_text(result.get("extracted_text")):
                score += Decimal("0.15")
            if result.get("case_no") or structured.get("payment_deadline") or structured.get("payment_term_days"):
                score += Decimal("0.05")
            return float(min(score, Decimal("0.99")))
        if event_type == "payment_screenshot" and cls._explicit_payment_confirmation(result.get("extracted_text")):
            return 0.95
        return None

    @staticmethod
    def _review_reasons(result: dict[str, Any]) -> list[str]:
        reasons = result.get("review_reasons")
        if not isinstance(reasons, list):
            reasons = []
        cleaned = [str(reason).strip()[:200] for reason in reasons if str(reason).strip()]
        if result.get("requires_review") and not cleaned:
            cleaned.append("识别结果要求人工复核")
        return cleaned

    @classmethod
    def _missing_critical_fields(cls, result: dict[str, Any]) -> list[str]:
        event_type = result.get("event_type") or "unknown"
        metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
        missing: list[str] = []

        def require(value: Any, label: str) -> None:
            if value in (None, "", [], {}):
                missing.append(f"缺少{label}")

        if event_type == "judgment":
            require(result.get("document_type"), "文书类型")
            require(result.get("plaintiff"), "原告")
            require(result.get("defendant"), "被告")
            require(structured.get("court_name"), "法院")
            if result.get("document_type") in {"判决书", "调解书"}:
                require(result.get("amount"), "金额")
        elif event_type == "court_notice":
            require(result.get("plaintiff"), "原告")
            require(result.get("defendant"), "被告")
            require(structured.get("court_name"), "法院")
            require(result.get("court_time"), "开庭时间")
        elif event_type == "repayment_agreement":
            require(result.get("plaintiff"), "债权人")
            require(result.get("defendant"), "债务人")
            require(result.get("amount"), "协议总额")
            if not cls._valid_installments(structured.get("repayment_plan")):
                missing.append("缺少有效分期计划")
        elif event_type == "payment_notice":
            require(result.get("amount"), "缴费金额")
            require(result.get("defendant") or structured.get("defendant"), "缴费当事人")
            require(structured.get("payment_type") or cls._payment_type_in_text(result.get("extracted_text")), "缴费类型")
        elif event_type == "payment_screenshot":
            require(result.get("amount"), "付款金额")
            if metadata.get("repayment_annotation"):
                require(result.get("plaintiff"), "债权人")
                require(result.get("defendant"), "债务人")
                require(metadata.get("repayment_agreement_event_id"), "关联还款协议")
            elif metadata.get("media_file_id") is not None:
                require(metadata.get("payment_notice_event_id"), "关联缴费通知")
        elif event_type == "unknown":
            missing.append("无法判断业务类型")
        return missing

    @classmethod
    def _valid_installments(cls, value: Any) -> bool:
        if not isinstance(value, dict) or not isinstance(value.get("installments"), list):
            return False
        installments = value["installments"]
        if not installments:
            return False
        return all(
            isinstance(item, dict)
            and bool(item.get("due_date"))
            and cls._positive_amount(item.get("amount"))
            for item in installments
        )

    @staticmethod
    def _positive_amount(value: Any) -> bool:
        try:
            return Decimal(str(value)) > 0
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def _payment_type_in_text(value: Any) -> str | None:
        text = str(value or "")
        return next(
            (label for label in ("案件受理费", "诉讼费", "公告费", "保全费", "执行费", "律师费", "法务费") if label in text),
            None,
        )

    @staticmethod
    def _explicit_payment_confirmation(value: Any) -> bool:
        return is_payment_done_text(str(value or ""))

    @staticmethod
    def _action_label(action: AutomationAction) -> str:
        return "提醒" if action == "remind" else "写入"
