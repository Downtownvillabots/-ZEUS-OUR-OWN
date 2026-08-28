"""Typed models owned by the media-indexing feature."""
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
    title: str
    normalized_title: str
    year: int | None
    resolution: str | None
    quality: str | None
    codec: str | None
    languages: tuple[str, ...]
    season: int | None
    episode: int | None
    is_series: bool

@dataclass(frozen=True, slots=True)
class DuplicateKey:
    file_unique_id: str | None
    file_size: int
    normalized_title: str
    year: int | None
    resolution: str | None
    quality: str | None
    language_key: str
    season: int | None
    episode: int | None
