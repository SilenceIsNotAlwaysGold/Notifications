import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.utils.datetime_utils import app_timezone, now_tz

CASE_NO_PATTERN = re.compile(
    r"(?:案号|案件编号)?[:：]?\s*([\(（]\s*\d{4}\s*[\)）](?:\s*[\u4e00-\u9fa5A-Za-z0-9])+\s*号)"
)
PLAINTIFF_PATTERN = re.compile(r"原告(?:人)?[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·、,，\s]{2,40})")
DEFENDANT_PATTERN = re.compile(r"被告(?:人)?[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·、,，\s]{2,40})")
LEADING_PARTY_PATTERN = re.compile(
    r"^\s*([\u4e00-\u9fa5·]{2,12})\s*[,，]\s*(?=(?:案号|我?(?:已经|已)|诉讼费|公告费|案件受理费))"
)
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

PAYMENT_NOTICE_KEYWORDS = ["需要缴费", "缴费通知", "缴费金额", "案件受理费", "诉讼费", "公告费", "开庭费", "缴纳"]
PAYMENT_DONE_KEYWORDS = [
    "已付款",
    "已支付",
    "支付成功",
    "转账成功",
    "已缴费",
    "已代缴",
    "已收款",
    "付款截图",
    "已交诉讼费",
    "已经交诉讼费",
    "诉讼费已交",
    "已交公告费",
    "公告费已交",
    "已经转账",
]

PAYMENT_FEE_PATTERN = r"(?:案件受理费|诉讼费|公告费|保全费|执行费|律师费|法务费|费用|款项)"
PAYMENT_DONE_PATTERN = re.compile(
    rf"(?:我|本人|我们|这边|客户|对方)?(?:已经|已)(?:付款|支付|代缴|转账)(?:了)?"
    rf"|(?:我|本人|我们|这边|客户|对方)?(?:已经|已)(?:交|缴|付)(?:了)?[^，。；;!?！？]{{0,12}}{PAYMENT_FEE_PATTERN}"
    rf"|{PAYMENT_FEE_PATTERN}[^，。；;!?！？]{{0,12}}(?:已经|已)?(?:交了|缴了|付了|付款了|支付了|代缴了|转账了|已交|已缴|已付|已支付|已代缴|已转账)"
)
PAYMENT_NOT_DONE_PATTERN = re.compile(
    r"(?:未|没|没有|尚未|还没|暂未)[^，。；;!?！？]{0,8}(?:交|缴|付|付款|支付|转账|到账)"
    r"|(?:是否|有没有|交没交|缴没缴|付没付|交了?吗|缴了?吗|付了?吗|支付了吗|转账了吗)"
)
COURT_KEYWORDS = ["传票", "开庭", "现场开庭"]
JUDGMENT_KEYWORDS = ["判决书", "民事判决书", "调解书", "民事调解书", "裁定书", "民事裁定书"]
DEFAULT_KEYWORDS = ["强制执行", "仲裁", "逾期"]
REPAYMENT_AGREEMENT_KEYWORDS = ["还款协议", "还款调解协议", "分期还款协议"]


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
        "document_type": extract_document_type(content),
        "plaintiff": extract_party(content, PLAINTIFF_PATTERN),
        "defendant": extract_party(content, DEFENDANT_PATTERN) or extract_leading_party(content),
        "court_time": extract_event_time(content),
        "requires_review": requires_review(content, event_type),
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
    return re.sub(r"\s+", "", match.group(1))


def extract_amounts(content: str) -> list[Decimal]:
    values: list[Decimal] = []
    for pattern in AMOUNT_PATTERNS:
        for match in pattern.findall(content):
            amount = Decimal(str(match).replace(",", "")).quantize(Decimal("0.01"))
            if amount not in values:
                values.append(amount)
    return values


def extract_document_type(content: str) -> str | None:
    if "调解书" in content:
        return "调解书"
    if "裁定书" in content:
        return "裁定书"
    if "判决书" in content:
        return "判决书"
    if "传票" in content:
        return "开庭传票"
    return None


def extract_party(content: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(content)
    if not match:
        return None
    value = re.split(r"[\n\r，,。；;]\s*", match.group(1).strip())[0]
    return value.strip(" ：:，,。；;") or None


def extract_leading_party(content: str) -> str | None:
    match = LEADING_PARTY_PATTERN.search(content)
    return match.group(1).strip() if match else None


def requires_review(content: str, event_type: str) -> bool:
    if event_type == "judgment":
        return not (extract_document_type(content) and extract_party(content, PLAINTIFF_PATTERN) and extract_party(content, DEFENDANT_PATTERN))
    if event_type == "court_notice":
        return extract_event_time(content) is None
    return False


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
    if contains_any(content, REPAYMENT_AGREEMENT_KEYWORDS):
        return "repayment_agreement"
    if is_payment_done_text(content, keyword_config=keyword_config):
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
    return is_payment_done_text(content, keyword_config=keyword_config) and contains_any(content, keywords["payment_notice"])


def is_payment_done_text(content: str, keyword_config: dict[str, list[str]] | None = None) -> bool:
    cleaned = " ".join((content or "").split())
    if not cleaned or PAYMENT_NOT_DONE_PATTERN.search(cleaned):
        return False
    keywords = _keyword_sets(keyword_config)
    return contains_any(cleaned, keywords["payment_done"]) or bool(PAYMENT_DONE_PATTERN.search(cleaned))


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
