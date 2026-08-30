"""
Validation utilities.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import Optional


USERNAME_RE = re.compile(
    r"^[A-Za-z0-9_]{5,32}$"
)

TELEGRAM_USERNAME_RE = re.compile(
    r"^@?[A-Za-z0-9_]{5,32}$"
)


def is_valid_telegram_id(
    value: object,
) -> bool:

    try:

        number = int(
            str(value).strip()
        )

    except (
        TypeError,
        ValueError,
    ):

        return False

    return (
        abs(number) >= 1
        and abs(number) <= 10**15
    )


def is_valid_username(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    username = str(
        value
    ).strip().lstrip("@")

    return bool(
        USERNAME_RE.fullmatch(
            username
        )
    )


def is_valid_telegram_username(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    return bool(
        TELEGRAM_USERNAME_RE.fullmatch(
            str(value).strip()
        )
    )


def is_valid_url(
    value: Optional[str],
    *,
    allowed_schemes: tuple[str, ...] = (
        "http",
        "https",
    ),
) -> bool:

    if not value:
        return False

    try:

        parsed = urlparse(
            str(value).strip()
        )

    except ValueError:

        return False

    return bool(
        parsed.scheme.lower()
        in {
            scheme.lower()
            for scheme in allowed_schemes
        }
        and parsed.netloc
    )


def is_valid_email(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    value = str(value).strip()

    if len(value) > 254:
        return False

    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            value,
        )
    )


def is_valid_file_id(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    value = str(value).strip()

    return (
        1 <= len(value) <= 1024
        and "\x00" not in value
    )


def is_valid_language_code(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    return bool(
        re.fullmatch(
            r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?",
            str(value).strip(),
        )
    )


__all__ = [
    "is_valid_telegram_id",
    "is_valid_username",
    "is_valid_telegram_username",
    "is_valid_url",
    "is_valid_email",
    "is_valid_file_id",
    "is_valid_language_code",
]