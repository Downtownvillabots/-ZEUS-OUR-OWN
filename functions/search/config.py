"""
Configuration for DOWNTOWN VILLA Search Feature.
"""

from __future__ import annotations

SEARCH_SESSION_TIMEOUT_SECONDS: int = 300
PAGE_SIZE: int = 5

DEFAULT_CAPTION_TEMPLATE: str = (
    "🎬 **{title}** ({year})\n\n"
    "🌐 **Language:** {language}\n"
    "🎞️ **Quality:** {resolution} {quality}\n"
    "💾 **Size:** {size_human}\n\n"
    "🏙️ *Downtown Villa Media*"
)
