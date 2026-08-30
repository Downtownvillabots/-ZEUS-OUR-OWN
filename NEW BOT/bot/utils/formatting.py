"""
Formatting utilities.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional


BYTE_UNITS = (
    "B",
    "KB",
    "MB",
    "GB",
    "TB",
    "PB",
)


def format_bytes(
    value: Optional[int | float],
    *,
    precision: int = 2,
) -> str:

    if value is None:
        return "0 B"

    size = max(
        0.0,
        float(value),
    )

    precision = max(
        0,
        int(precision),
    )

    unit_index = 0

    while (
        size >= 1024
        and unit_index < len(BYTE_UNITS) - 1
    ):

        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} B"

    return (
        f"{size:.{precision}f} "
        f"{BYTE_UNITS[unit_index]}"
    )


def format_number(
    value: Optional[int | float | Decimal],
) -> str:

    if value is None:
        return "0"

    if isinstance(value, Decimal):

        if value == value.to_integral_value():
            return f"{int(value):,}"

        return f"{value:,}"

    if isinstance(value, float):

        if value.is_integer():
            return f"{int(value):,}"

        return f"{value:,.2f}"

    return f"{int(value):,}"


def format_duration(
    seconds: Optional[int | float],
) -> str:

    if seconds is None:
        return "0s"

    total = max(
        0,
        int(seconds),
    )

    days, remainder = divmod(
        total,
        86400,
    )

    hours, remainder = divmod(
        remainder,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if seconds or not parts:
        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts)


def format_timedelta(
    value: Optional[timedelta],
) -> str:

    if value is None:
        return "0s"

    return format_duration(
        value.total_seconds()
    )


def format_percentage(
    value: Optional[float],
    *,
    precision: int = 1,
) -> str:

    if value is None:
        value = 0.0

    return (
        f"{float(value):.{precision}f}%"
    )


def format_price(
    amount: Optional[int | float | Decimal],
    currency: str = "USD",
) -> str:

    if amount is None:
        amount = 0

    symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "INR": "₹",
        "JPY": "¥",
    }

    symbol = symbols.get(
        currency.upper(),
        "",
    )

    if symbol:
        return f"{symbol}{float(amount):,.2f}"

    return (
        f"{float(amount):,.2f} "
        f"{currency.upper()}"
    )


__all__ = [
    "format_bytes",
    "format_number",
    "format_duration",
    "format_timedelta",
    "format_percentage",
    "format_price",
]