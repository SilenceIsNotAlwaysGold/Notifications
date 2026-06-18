import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.utils.datetime_utils import app_timezone, now_tz

CASE_NO_PATTERN = re.compile(r"(?:案号|案件编号)?[:：]?\s*[\(（]\d{4}[\)）][\u4e00-\u9fa5A-Za-z0-9]+号")
AMOUNT_PATTERNS = [
    re.compile(r"[¥￥]\s*([\d,]+(?:\.\d{1,2})?)"),
    re.compile(r"人民币\s*([\d,]+(?:\.\d{1,2})?)"),
    re.compile(r"(?:缴费金额|诉讼费|公告费|开庭费)?[:：]?\s*([\d,]+(?:\.\d{1,2})?)\s*元"),
]
FULL_DATETIME_PATTERNS = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})[:：](\d{2})"),
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})"),
]
CN_TIME_PATTERN = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(上午|下午)?\s*(\d{1,2})点")

PAYMENT_NOTICE_KEYWORDS = ["需要缴费", "缴费通知", "缴费金额", "诉讼费", "公告费", "开庭费", "缴纳"]
PAYMENT_DONE_KEYWORDS = ["已付款", "已支付", "支付成功", "转账成功", "已缴费", "付款截图"]
COURT_KEYWORDS = ["传票", "开庭", "现场开庭"]
JUDGMENT_KEYWORDS = ["判决书", "民事判决书", "裁定书"]
DEFAULT_KEYWORDS = ["强制执行", "仲裁", "逾期"]


def parse_legal_text(text: str | None, keyword_config: dict[str, list[str]] | None = None) -> dict[str, Any]:
    content = text or ""
    keywords = _keyword_sets(keyword_config)
    amounts = extract_amounts(content)
    event_type = extract_event_type(content, keywords)
    event_types = [] if event_type == "unknown" else [event_type]
    return {
        "case_no": extract_case_no(content),
        "amounts": amounts,
        "amount": amounts[0] if amounts else None,
        "keywords": matched_keywords(content, keywords),
        "event_type": event_type,
        "event_types": event_types,
        "event_time": extract_event_time(content),
        "extracted_text": content,
        "metadata": {"parser": "regex_v2", "payment_keyword_conflict": has_payment_conflict(content, keywords)},
    }


def extract_case_no(content: str) -> str | None:
    match = CASE_NO_PATTERN.search(content)
    if not match:
        return None
    case_no_match = re.search(r"[\(（]\d{4}[\)）][\u4e00-\u9fa5A-Za-z0-9]+号", match.group(0))
    return case_no_match.group(0) if case_no_match else match.group(0)


def extract_amounts(content: str) -> list[Decimal]:
    values: list[Decimal] = []
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.findall(content):
            amount = Decimal(str(match).replace(",", "")).quantize(Decimal("0.01"))
            if amount not in values:
                values.append(amount)
    return values


def extract_event_time(content: str) -> datetime | None:
    for pattern in FULL_DATETIME_PATTERNS:
        match = pattern.search(content)
        if match:
            year, month, day, hour, minute = [int(part) for part in match.groups()]
            return datetime(year, month, day, hour, minute, tzinfo=app_timezone())

    match = CN_TIME_PATTERN.search(content)
    if not match:
        return None
    year_text, month, day, period, hour = match.groups()
    year = int(year_text) if year_text else now_tz().year
    parsed_hour = int(hour)
    if period == "下午" and parsed_hour < 12:
        parsed_hour += 12
    return datetime(year, int(month), int(day), parsed_hour, 0, tzinfo=app_timezone())


def extract_event_type(content: str, keyword_config: dict[str, list[str]] | None = None) -> str:
    keywords = _keyword_sets(keyword_config)
    if contains_any(content, keywords["payment_done"]):
        return "payment_screenshot"
    if contains_any(content, keywords["payment_notice"]):
        return "payment_notice"
    if contains_any(content, keywords["court_notice"]):
        return "court_notice"
    if contains_any(content, keywords["judgment"]):
        return "judgment"
    if contains_any(content, keywords["default"]):
        return "keyword"
    return "unknown"


def matched_keywords(content: str, keyword_config: dict[str, list[str]] | None = None) -> list[str]:
    keyword_sets = _keyword_sets(keyword_config)
    all_keywords = (
        keyword_sets["payment_done"]
        + keyword_sets["payment_notice"]
        + keyword_sets["court_notice"]
        + keyword_sets["judgment"]
        + keyword_sets["default"]
    )
    return [keyword for keyword in all_keywords if keyword in content]


def has_payment_conflict(content: str, keyword_config: dict[str, list[str]] | None = None) -> bool:
    keywords = _keyword_sets(keyword_config)
    return contains_any(content, keywords["payment_done"]) and contains_any(content, keywords["payment_notice"])


def contains_any(content: str, keywords: list[str]) -> bool:
    return any(keyword in content for keyword in keywords)


def _keyword_sets(keyword_config: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    defaults = {
        "payment_notice": PAYMENT_NOTICE_KEYWORDS,
        "payment_done": PAYMENT_DONE_KEYWORDS,
        "court_notice": COURT_KEYWORDS,
        "judgment": JUDGMENT_KEYWORDS,
        "default": DEFAULT_KEYWORDS,
    }
    if not keyword_config:
        return {key: list(value) for key, value in defaults.items()}
    merged = {key: list(value) for key, value in defaults.items()}
    for key, values in keyword_config.items():
        if key in merged and isinstance(values, list):
            merged[key] = [str(value) for value in values]
    return merged
