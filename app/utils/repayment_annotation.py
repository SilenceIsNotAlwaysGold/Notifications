import re
from decimal import Decimal, InvalidOperation
from typing import Any


_SEPARATOR_PATTERN = re.compile(r"\s*[+＋|｜]\s*")
_SEQUENCE_PATTERN = re.compile(r"第\s*(\d{1,3})\s*期")
_AMOUNT_PATTERN = re.compile(r"(?:金额\s*[:：]?\s*)?[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*元?")


def parse_repayment_annotation(text: str | None) -> dict[str, Any] | None:
    """Parse a caption such as 原告甲+被告乙+第2期还款+金额1000元."""
    content = " ".join((text or "").strip().split())
    if not content or "还款" not in content:
        return None
    sequence_match = _SEQUENCE_PATTERN.search(content)
    if not sequence_match:
        return None

    parts = [part.strip() for part in _SEPARATOR_PATTERN.split(content) if part.strip()]
    if len(parts) < 4:
        return None

    plaintiff = _labeled_value(parts, "原告") or _plain_party(parts[0], "原告")
    defendant = _labeled_value(parts, "被告") or _plain_party(parts[1], "被告")
    amount = _extract_amount(parts)
    sequence = int(sequence_match.group(1))
    if not plaintiff or not defendant or amount is None or sequence <= 0:
        return None
    return {
        "plaintiff": plaintiff,
        "defendant": defendant,
        "installment_sequence": sequence,
        "amount": amount,
        "raw_text": content[:1000],
    }


def repayment_annotation_from_context(context_messages: list[dict[str, Any]] | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for message in context_messages or []:
        if message.get("position") != "after" or message.get("msg_type") != "text":
            continue
        annotation = parse_repayment_annotation(str(message.get("content") or ""))
        if annotation:
            return annotation, message
    return None


def _labeled_value(parts: list[str], label: str) -> str | None:
    for part in parts:
        if part.startswith(label):
            return _clean_party(part[len(label) :])
    return None


def _plain_party(value: str, label: str) -> str | None:
    return _clean_party(value.removeprefix(label))


def _clean_party(value: str) -> str | None:
    cleaned = value.strip(" :：,，。;；")
    if not cleaned or len(cleaned) > 128 or _SEQUENCE_PATTERN.search(cleaned) or "金额" in cleaned:
        return None
    return cleaned


def _extract_amount(parts: list[str]) -> Decimal | None:
    candidates = [part for part in parts if "金额" in part]
    candidates.extend(part for part in parts if "元" in part and "第" not in part and part not in candidates)
    for part in candidates:
        match = _AMOUNT_PATTERN.search(part)
        if not match:
            continue
        try:
            amount = Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        except InvalidOperation:
            continue
        if amount > 0:
            return amount
    return None
