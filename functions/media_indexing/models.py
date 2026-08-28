"""Domain models. Telegram/database details stay outside these objects."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class IndexMode(str, Enum):
    MOVIES = "movies"
    SERIES = "series"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class ParsedMedia:
    original_name: str
    clean_name: str
    title: str
    normalized_title: str
    year: int | None
    resolution: str | None
    quality: str | None
    codec: str | None
    languages: tuple[str, ...]
    audio_languages: tuple[str, ...]
    subtitle_languages: tuple[str, ...]
    season: int | None
    episode: int | None
    is_series: bool


@dataclass(slots=True)
class IndexStats:
    scanned: int = 0
    accepted: int = 0
    saved: int = 0
    duplicates: int = 0
    filtered: int = 0
    unsupported: int = 0
    errors: int = 0
