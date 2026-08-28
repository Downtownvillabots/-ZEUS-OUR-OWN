"""Environment-controlled configuration for Media Indexing."""
from __future__ import annotations
import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def channel_ids(value: str | None) -> tuple[int, ...]:
    result = []
    for item in (value or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            continue
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True, slots=True)
class IndexingConfig:
    database_channels: tuple[int, ...]
    live_enabled: bool
    historical_enabled: bool
    batch_size: int
    concurrency: int
    progress_every: int
    max_scan_messages: int
    rotation_mb: int
    max_duplicate_candidates: int


def load_config() -> IndexingConfig:
    return IndexingConfig(
        database_channels=channel_ids(os.getenv("DATABASE_CHANNELS")),
        live_enabled=_bool("LIVE_INDEXING_ENABLED", True),
        historical_enabled=_bool("HISTORICAL_INDEXING_ENABLED", True),
        batch_size=max(25, _int("INDEX_BATCH_SIZE", 200)),
        concurrency=max(1, _int("INDEX_MAX_CONCURRENCY", 20)),
        progress_every=max(1, _int("INDEX_PROGRESS_EVERY", 100)),
        max_scan_messages=max(1, _int("INDEX_MAX_SCAN_MESSAGES", 1_000_000)),
        rotation_mb=max(100, _int("MEDIA_DATABASE_ROTATION_MB", 400)),
        max_duplicate_candidates=max(10, _int("MAX_DUPLICATE_CANDIDATES", 100)),
    )
