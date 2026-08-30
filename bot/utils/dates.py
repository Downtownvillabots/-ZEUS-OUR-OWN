"""
Date/time helpers.

All application timestamps are UTC-aware.
"""

from __future__ import annotations

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import Optional


UTC = timezone.utc


def utc_now() -> datetime:

    return datetime.now(
        UTC
    )


def ensure_utc(
    value: datetime,
) -> datetime:

    if value.tzinfo is None:

        return value.replace(
            tzinfo=UTC
        )

    return value.astimezone(
        UTC
    )


def add_days(
    value: Optional[datetime] = None,
    days: int = 1,
) -> datetime:

    base = (
        utc_now()
        if value is None
        else ensure_utc(value)
    )

    return (
        base
        + timedelta(days=int(days))
    )


def add_minutes(
    value: Optional[datetime] = None,
    minutes: int = 1,
) -> datetime:

    base = (
        utc_now()
        if value is None
        else ensure_utc(value)
    )

    return (
        base
        + timedelta(
            minutes=int(minutes)
        )
    )


def add_seconds(
    value: Optional[datetime] = None,
    seconds: int = 1,
) -> datetime:

    base = (
        utc_now()
        if value is None
        else ensure_utc(value)
    )

    return (
        base
        + timedelta(
            seconds=int(seconds)
        )
    )


def is_expired(
    expires_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> bool:

    if expires_at is None:
        return False

    current = (
        utc_now()
        if now is None
        else ensure_utc(now)
    )

    return (
        ensure_utc(expires_at)
        <= current
    )


def seconds_until(
    target: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> int:

    if target is None:
        return 0

    current = (
        utc_now()
        if now is None
        else ensure_utc(now)
    )

    seconds = (
        ensure_utc(target)
        - current
    ).total_seconds()

    return max(
        0,
        int(seconds),
    )


def isoformat(
    value: Optional[datetime],
) -> Optional[str]:

    if value is None:
        return None

    return ensure_utc(
        value
    ).isoformat()


def parse_iso(
    value: Optional[str],
) -> Optional[datetime]:

    if not value:
        return None

    try:

        parsed = datetime.fromisoformat(
            str(value)
        )

    except ValueError:

        return None

    return ensure_utc(
        parsed
    )


__all__ = [
    "UTC",
    "utc_now",
    "ensure_utc",
    "add_days",
    "add_minutes",
    "add_seconds",
    "is_expired",
    "seconds_until",
    "isoformat",
    "parse_iso",
]