"""MongoDB connection configuration.

DATABASE_1_URI is the bot/core database. MEDIA_DATABASE_URIS contains
Database 2, Database 3, Database 4... in write/search order.
"""
from __future__ import annotations
import os


def media_database_uris() -> tuple[str, ...]:
    raw = os.getenv("MEDIA_DATABASE_URIS", "")
    return tuple(x.strip() for x in raw.split(",") if x.strip())


def core_database_uri() -> str:
    return os.getenv("DATABASE_1_URI", "").strip()
