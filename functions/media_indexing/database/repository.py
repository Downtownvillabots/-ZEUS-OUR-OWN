"""MongoDB repository used by the shared indexing processor."""
from __future__ import annotations
from .manager import MongoMediaManager
from ..duplicate.policy import is_duplicate
from ..models import ParsedMedia


class MongoMediaRepository:
    def __init__(self, manager: MongoMediaManager, max_candidates: int = 100):
        self.manager = manager
        self.max_candidates = max_candidates

    async def duplicate_exists(
        self,
        media: ParsedMedia,
        *,
        file_size: int,
        file_unique_id: str | None,
    ) -> bool:
        for item in self.manager.databases:
            cursor = item.collection.find(
                {
                    "normalized_title": media.normalized_title,
                    "file_size": int(file_size),
                },
                limit=self.max_candidates,
            )
            async for candidate in cursor:
                if is_duplicate(
                    media,
                    candidate,
                    file_size=file_size,
                    file_unique_id=file_unique_id,
                ):
                    return True
        return False

    async def insert(self, record: dict) -> int:
        target = await self.manager.writable()
        result = await target.collection.insert_one(record)
        return target.number
