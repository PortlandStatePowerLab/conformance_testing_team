"""Pacific civil-time formatting for human-readable records and file names."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")


def pacific_datetime(value: datetime | None = None) -> datetime:
    """Return an aware datetime converted to Pacific civil time."""
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return current.astimezone(PACIFIC_TIMEZONE)


def pacific_timestamp(value: datetime | None = None) -> str:
    """Return ISO-8601 Pacific time with milliseconds and a UTC offset."""
    return pacific_datetime(value).isoformat(timespec="milliseconds")


def pacific_filename_timestamp(value: datetime | None = None) -> str:
    """Return a filesystem-safe Pacific timestamp with PST/PDT designation."""
    return pacific_datetime(value).strftime("%Y_%m_%d_%H%M%S_%Z")
