import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import dateparser

UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def _aware(d: datetime) -> datetime:
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def parse_date(value, now: datetime | None = None) -> datetime | None:
    """Normalize any date-like value to an aware UTC datetime, or None.
    Handles epoch seconds/milliseconds, ISO-8601, RFC-2822 and relative text
    such as '2 hours ago'. Naive timestamps are assumed to be UTC."""
    now = now or now_utc()
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", value.strip())):
        n = float(value)
        if n > 1e11:
            n /= 1000.0          # milliseconds
        try:
            return datetime.fromtimestamp(n, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    try:
        return _aware(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    try:
        return _aware(parsedate_to_datetime(s))
    except (TypeError, ValueError):
        pass
    d = dateparser.parse(s, settings={
        "RELATIVE_BASE": now.astimezone(UTC).replace(tzinfo=None),
        "TIMEZONE": "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "past",
    })
    return d.astimezone(UTC) if d else None