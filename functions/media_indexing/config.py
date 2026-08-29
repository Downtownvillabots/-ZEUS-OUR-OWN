"""
Central configuration reader for Media Indexing system.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_int_csv(value: str) -> list[int]:
    result = []
    for item in value.split(","):
        item = item.strip()
        if item:
            try:
                result.append(int(item))
            except ValueError:
                pass
    return result


@dataclass(frozen=True, slots=True)
class MediaIndexingConfig:
    core_db_uri: str
    media_db_uris: list[str]
    rotation_mb: float
    database_channels: list[int]

    @classmethod
    def from_env(cls) -> MediaIndexingConfig:
        core_uri = os.getenv("DATABASE_1_URI", "").strip() or os.getenv("MONGODB_URI", "").strip()
        if not core_uri:
            raise RuntimeError("DATABASE_1_URI (or MONGODB_URI) must be provided in environment.")

        media_uris_raw = os.getenv("MEDIA_DATABASE_URIS", "").strip()
        media_uris = _split_csv(media_uris_raw) if media_uris_raw else [core_uri]

        rotation_mb = float(os.getenv("MEDIA_DATABASE_ROTATION_MB", "400").strip() or 400)
        channels = _split_int_csv(os.getenv("DATABASE_CHANNELS", ""))

        return cls(
            core_db_uri=core_uri,
            media_db_uris=media_uris,
            rotation_mb=rotation_mb,
            database_channels=channels,
        )
