"""All indexing-specific configuration lives here."""
from __future__ import annotations
import os
from dataclasses import dataclass


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

@dataclass(frozen=True, slots=True)
class IndexingConfig:
    batch_size: int = env_int("INDEX_BATCH_SIZE", 200)
    progress_every: int = env_int("INDEX_PROGRESS_EVERY", 200)
    max_concurrency: int = env_int("INDEX_MAX_CONCURRENCY", 25)
    max_scan_messages: int = env_int("INDEX_MAX_SCAN_MESSAGES", 1_000_000)
