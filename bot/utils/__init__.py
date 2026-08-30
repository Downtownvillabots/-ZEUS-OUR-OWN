"""
bot.utils

Shared utility functions used across the bot.
"""

from .text import (
    clean_text,
    normalize_text,
    truncate_text,
    escape_markdown,
)

from .formatting import (
    format_bytes,
    format_duration,
    format_number,
)

from .validators import (
    is_valid_url,
    is_valid_telegram_id,
    is_valid_username,
)

from .crypto import (
    generate_token,
    hash_token,
    verify_token,
)

from .dates import (
    utc_now,
    add_days,
    add_minutes,
    is_expired,
)

__all__ = [
    "clean_text",
    "normalize_text",
    "truncate_text",
    "escape_markdown",

    "format_bytes",
    "format_duration",
    "format_number",

    "is_valid_url",
    "is_valid_telegram_id",
    "is_valid_username",

    "generate_token",
    "hash_token",
    "verify_token",

    "utc_now",
    "add_days",
    "add_minutes",
    "is_expired",
]
