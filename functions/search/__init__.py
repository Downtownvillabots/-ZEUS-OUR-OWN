"""
Search Feature Module Initialization.
Diagnosed & Repaired for DOWNTOWN VILLA.
"""
from __future__ import annotations

from app.logging import get_logger
from app.runtime import Runtime
from functions.media_indexing.database.manager import DatabaseManager
from functions.search.handler import register_search_handlers

LOGGER = get_logger(__name__)


def register(runtime: Runtime) -> None:
    LOGGER.info("SEARCH FEATURE INITIALIZING...")
    
    # Initialize shared database manager for search querying across sharded media databases
    db_manager = DatabaseManager(
        core_uri=runtime.config.database_1_uri,
        media_uris=runtime.config.media_database_uris,
        rotation_mb=runtime.config.media_database_rotation_mb,
    )
    
    register_search_handlers(runtime.client, db_manager)
    LOGGER.info("SEARCH FEATURE INITIALIZED SUCCESSFULLY")
