from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def app_timezone() -> ZoneInfo:
    return get_settings().tzinfo


def now_tz() -> datetime:
    return datetime.now(app_timezone())


def today_tz() -> date:
    return now_tz().date()


def parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value)
    return ensure_aware(parsed)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=app_timezone())
    return value.astimezone(app_timezone())


def start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=app_timezone())
