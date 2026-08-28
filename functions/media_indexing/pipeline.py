"""Pure indexing pipeline helpers; no Telegram/database side effects."""
from __future__ import annotations
from .models import IndexMode
from .metadata.parser import parse


def classify_filename(filename: str, mode: IndexMode, caption: str | None = None):
    media = parse(filename, caption)
    if mode is IndexMode.MOVIES and media.is_series:
        return None
    if mode is IndexMode.SERIES and not media.is_series:
        return None
    return media
