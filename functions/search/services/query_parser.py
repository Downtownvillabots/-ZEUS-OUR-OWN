"""
Search query cleaner and visual element remover.
"""

from __future__ import annotations

import re

NOISE_PATTERNS = [
    r"@\w+",
    r"https?://\S+",
    r"www\.\S+",
    r"[\[\]\(\)\{\}\._\-+]",
]


def clean_search_query(raw_query: str) -> str:
    """Cleans channel noise, URLs, tags, and unnecessary punctuation from queries."""
    text = raw_query.strip()
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    
    cleaned = " ".join(text.split())
    return cleaned if cleaned else raw_query.strip()
