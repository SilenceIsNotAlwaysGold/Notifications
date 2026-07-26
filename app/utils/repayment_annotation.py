import re
from decimal import Decimal, InvalidOperation
from typing import Any


_SEPARATOR_PATTERN = re.compile(r"\s*[+＋|｜]\s*")
_SEQUENCE_PATTERN = re.compile(r"第\s*(\d{1,3}|[一二三四五六七八九十百]{1,4})\s*期")
_AMOUNT_PATTERN = re.compile(r"(?:金额\s*[:：]?\s*)?[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*元?")
_COMPACT_PAYMENT_MARKER = re.compile(
    r"(?:已\s*)?(?:还款|付款|支付)?\s*第\s*(?:\d{1,3}|[一二三四五六七八九十百]{1,4})\s*期(?:\s*(?:还款|付款|支付))?"
)
_PAYMENT_WORD_PATTERN = re.compile(r"还款|付款|支付|结清|已完结|部分还款")
_FULL_SETTLEMENT_PATTERN = re.compile(r"一次性结清|全部结清|全额结清|已结清")
_PARTIAL_PAYMENT_PATTERN = re.compile(r"部分还款|部分付款|一期的一部分")
_COMPLETED_PATTERN = re.compile(r"案件已完结|已完结")
_LABELED_PARTIES_PATTERN = re.compile(
    r"^(?:原告(?:人)?\s*[:：]?)?\s*(.+?)\s*[,，;；]\s*被告(?:人)?\s*[:：]?\s*(.+?)(?=[,，;；]|$)"
)
_PARTY_SUFFIX_PATTERN = re.compile(
    r"^(.+?(?:股份有限公司|有限责任公司|有限公司|集团公司|合作社|"
    r"商行(?:\s*[（(]个体工商户[）)])?|经营部|工作室|服务部|事务所|中心|店))"
    r"[\s,，、:：+＋]*(.{2,128})$"
)


def parse_repayment_annotation(text: str | None) -> dict[str, Any] | None:
    """Parse a caption such as 原告甲+被告乙+第2期还款+金额1000元."""
    content = " ".join((text or "").strip().split())
    if not content or not _PAYMENT_WORD_PATTERN.search(content):
        return None
    sequence_match = _SEQUENCE_PATTERN.search(content)

    parts = [part.strip() for part in _SEPARATOR_PATTERN.split(content) if part.strip()]
    plaintiff, defendant = _extract_parties(content, parts)
    amount = _extract_amount(parts) or _extract_payment_amount(content, sequence_match.end() if sequence_match else None)
    sequence = _parse_sequence(sequence_match.group(1)) if sequence_match else None
    if not plaintiff or not defendant or amount is None or (sequence is not None and sequence <= 0):
        return None
    return {
        "plaintiff": plaintiff,
        "defendant": defendant,
        "installment_sequence": sequence,
        "amount": amount,
        "payment_kind": _payment_kind(content, sequence),
        "raw_text": content[:1000],
    }


def _parse_sequence(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "百" in value:
        hundreds, remainder = value.split("百", 1)
        return digits.get(hundreds, 1) * 100 + _parse_sequence(remainder) if remainder else digits.get(hundreds, 1) * 100
    if "十" in value:
        tens, units = value.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return digits.get(value, 0)


def _extract_parties(content: str, parts: list[str]) -> tuple[str | None, str | None]:
    if len(parts) >= 2:
        plaintiff = _labeled_value(parts, "原告") or _plain_party(parts[0], "原告")
        defendant = _labeled_value(parts, "被告") or _plain_party(parts[1], "被告")
        if plaintiff and defendant:
            return plaintiff, defendant

    labeled = _LABELED_PARTIES_PATTERN.match(content)
    if labeled:
        return _clean_party(labeled.group(1)), _clean_party(labeled.group(2))

    marker_positions = [match.start() for pattern in (_COMPACT_PAYMENT_MARKER, _FULL_SETTLEMENT_PATTERN, _PARTIAL_PAYMENT_PATTERN, _COMPLETED_PATTERN) if (match := pattern.search(content))]
    amount_before_status = re.search(r"[¥￥]?\s*[\d,]+(?:\.\d{1,2})?\s*元?\s*(?=一次性结清|全部结清|全额结清|案件已完结)", content)
    if amount_before_status:
        marker_positions.append(amount_before_status.start())
    prefix = content[: min(marker_positions)].strip(" :：,，。;；+＋-—、") if marker_positions else ""
    prefix = re.sub(r"^(?:原告(?:人)?\s*[:：]?)", "", prefix).strip()
    prefix = re.sub(r"\s*被告(?:人)?\s*[:：]?\s*", " ", prefix, count=1).strip()

    split_parts = [part.strip() for part in re.split(r"\s*[+＋|｜、-]\s*", prefix) if part.strip()]
    if len(split_parts) >= 2:
        return _clean_party(split_parts[0]), _clean_party(split_parts[1])

    match = _PARTY_SUFFIX_PATTERN.match(prefix)
    if not match:
        return None, None
    return _clean_party(match.group(1)), _clean_party(match.group(2))


def repayment_annotation_from_context(context_messages: list[dict[str, Any]] | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    matches: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for message in context_messages or []:
        if message.get("position") not in {"before", "after"} or message.get("msg_type") != "text":
            continue
        distance = float(message.get("distance_seconds") or 0)
        if distance > 10 * 60:
            continue
        annotation = parse_repayment_annotation(str(message.get("content") or ""))
        if annotation:
            matches.append((distance, annotation, message))
    if not matches:
        return None
    _, annotation, message = min(matches, key=lambda item: (item[0], int(item[2].get("message_id") or 0)))
    return annotation, message


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


def _extract_payment_amount(content: str, sequence_end: int | None) -> Decimal | None:
    if sequence_end is not None:
        tail = re.sub(r"^\s*(?:还款|付款|支付)\s*", "", content[sequence_end:])
        amount = _decimal_match(_AMOUNT_PATTERN.search(tail))
        if amount:
            return amount
    patterns = (
        re.compile(r"(?:金额|还款|付款|支付)\s*[:：]?\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*元?"),
        re.compile(r"[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*元?\s*(?:一次性结清|全部结清|全额结清)"),
    )
    for pattern in patterns:
        amount = _decimal_match(pattern.search(content))
        if amount:
            return amount
    candidates = list(re.finditer(r"(?<!第)(?<!\d)([\d,]+(?:\.\d{1,2})?)(?!\s*期)", content))
    return _decimal_match(candidates[-1]) if candidates else None


def _decimal_match(match: re.Match[str] | None) -> Decimal | None:
    if not match:
        return None
    try:
        amount = Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _payment_kind(content: str, sequence: int | None) -> str:
    if _COMPLETED_PATTERN.search(content):
        return "completed"
    if _FULL_SETTLEMENT_PATTERN.search(content):
        return "full_settlement"
    if _PARTIAL_PAYMENT_PATTERN.search(content):
        return "partial_payment"
    return "installment" if sequence is not None else "payment"
