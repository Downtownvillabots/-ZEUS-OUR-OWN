"""
Text manipulation utilities.
"""

from __future__ import annotations

import re
import unicodedata
from html import escape as html_escape
from typing import Optional


WHITESPACE_RE = re.compile(r"\s+")
URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.IGNORECASE,
)


def clean_text(
    value: Optional[str],
    *,
    strip: bool = True,
) -> str:

    if value is None:
        return ""

    text = str(value)

    text = text.replace(
        "\x00",
        "",
    )

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    text = WHITESPACE_RE.sub(
        " ",
        text,
    )

    if strip:
        text = text.strip()

    return text


def normalize_text(
    value: Optional[str],
) -> str:

    text = clean_text(value)

    text = text.casefold()

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    return text


def truncate_text(
    value: Optional[str],
    maximum: int,
    *,
    suffix: str = "...",
) -> str:

    text = clean_text(value)

    maximum = max(
        0,
        int(maximum),
    )

    if len(text) <= maximum:
        return text

    if maximum <= len(suffix):
        return suffix[:maximum]

    return (
        text[
            : maximum - len(suffix)
        ].rstrip()
        + suffix
    )


def escape_markdown(
    value: Optional[str],
    *,
    version: int = 2,
) -> str:

    text = "" if value is None else str(value)

    if version == 1:

        characters = (
            "_*`["
        )

    elif version == 2:

        characters = (
            r"_*[]()~`>#+-=|{}.!"
        )

    else:

        raise ValueError(
            "Markdown version must be 1 or 2."
        )

    output = []

    for char in text:

        if char in characters:
            output.append("\\")
        
        output.append(char)

    return "".join(output)


def escape_html(
    value: Optional[str],
) -> str:

    return html_escape(
        "" if value is None else str(value),
        quote=False,
    )


def contains_url(
    value: Optional[str],
) -> bool:

    if not value:
        return False

    return bool(
        URL_RE.search(
            str(value)
        )
    )


def extract_urls(
    value: Optional[str],
) -> list[str]:

    if not value:
        return []

    return URL_RE.findall(
        str(value)
    )


def remove_urls(
    value: Optional[str],
) -> str:

    if not value:
        return ""

    return clean_text(
        URL_RE.sub(
            "",
            str(value),
        )
    )


def safe_filename_text(
    value: Optional[str],
    *,
    maximum: int = 255,
) -> str:

    text = clean_text(value)

    text = re.sub(
        r'[<>:"/\\|?*\x00-\x1F]',
        "_",
        text,
    )

    text = text.strip(
        " ."
    )

    if not text:
        text = "file"

    return truncate_text(
        text,
        maximum,
        suffix="",
    )


__all__ = [
    "clean_text",
    "normalize_text",
    "truncate_text",
    "escape_markdown",
    "escape_html",
    "contains_url",
    "extract_urls",
    "remove_urls",
    "safe_filename_text",
]