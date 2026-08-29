"""
Multi-Stage Layered Duplicate Detection Policy.
"""

from __future__ import annotations

from typing import Any
from functions.media_indexing.database.manager import DatabaseManager


class DuplicatePolicy:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    async def is_duplicate(self, file_unique_id: str, meta: Any, file_size: int) -> tuple[bool, str]:
        # Stage 1: Check unique ID across shards
        id_match = await self.db_manager.find_in_all_shards({"file_unique_id": file_unique_id}, limit=1)
        if id_match:
            return True, "EXACT_UNIQUE_ID"

        # Stage 2: Check normalized title, size, year, season/episode match
        meta_query: dict[str, Any] = {
            "normalized_title": meta.normalized_title,
            "file_size": file_size,
        }
        if meta.year:
            meta_query["year"] = meta.year
        if meta.is_series:
            meta_query["season"] = meta.season
            meta_query["episode"] = meta.episode

        meta_match = await self.db_manager.find_in_all_shards(meta_query, limit=1)
        if meta_match:
            return True, "METADATA_AND_SIZE_MATCH"

        return False, "UNIQUE"
