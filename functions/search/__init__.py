"""
Search Feature Module Initialization.
"""
from __future__ import annotations

from app.logging import get_logger
from app.runtime import Runtime
from functions.media_indexing.database.manager import DatabaseManager
from functions.search.handler import register_search_handlers

LOGGER = get_logger(__name__)


def register(runtime: Runtime) -> None:
    LOGGER.info("SEARCH FEATURE INITIALIZING...")

    cfg = runtime.config

    # Safe dynamic extraction matching your environment variable names
    core_uri = (
        getattr(cfg, "database_1_uri", None)
        or getattr(cfg, "DATABASE_1_URI", None)
        or getattr(cfg, "db_uri", "")
    )

    media_uris = (
        getattr(cfg, "media_database_uris", None)
        or getattr(cfg, "MEDIA_DATABASE_URIS", None)
        or []
    )

    rotation_mb = (
        getattr(cfg, "media_database_rotation_mb", None)
        or getattr(cfg, "MEDIA_DATABASE_ROTATION_MB", None)
        or 400.0
    )

    # Initialize shared database manager
    db_manager = DatabaseManager(
        core_uri=core_uri,
        media_uris=media_uris,
        rotation_mb=rotation_mb,
    )

    register_search_handlers(runtime.client, db_manager)
    LOGGER.info("SEARCH FEATURE INITIALIZED SUCCESSFULLY")
