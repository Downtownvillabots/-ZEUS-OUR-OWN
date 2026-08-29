"""
MongoDB Sharding and Auto-Rotation Manager.
"""

from __future__ import annotations

import asyncio
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, TEXT, IndexModel

from app.logging import get_logger

LOGGER = get_logger(__name__)


class DatabaseManager:
    def __init__(self, core_uri: str, media_uris: list[str], rotation_mb: float = 400.0) -> None:
        self.core_uri = core_uri
        self.media_uris = media_uris if media_uris else [core_uri]
        self.rotation_bytes = int(rotation_mb * 1024 * 1024)

        self._core_client: AsyncIOMotorClient | None = None
        self._media_clients: list[AsyncIOMotorClient] = []

        self.active_db_index: int = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Initializes database connections and prepares indexes."""
        self._core_client = AsyncIOMotorClient(self.core_uri)
        self._media_clients = [AsyncIOMotorClient(uri) for uri in self.media_uris]

        for client in self._media_clients:
            db = client.get_database()
            await self._setup_indexes(db)

        await self._select_active_shard()

    async def _setup_indexes(self, db: AsyncIOMotorDatabase) -> None:
        indexes = [
            IndexModel([("file_unique_id", ASCENDING)], unique=True, sparse=True),
            IndexModel([("normalized_title", ASCENDING), ("file_size", ASCENDING)]),
            IndexModel([("normalized_title", TEXT), ("caption", TEXT)]),
            IndexModel([("is_series", ASCENDING), ("season", ASCENDING), ("episode", ASCENDING)]),
        ]
        try:
            await db.media.create_indexes(indexes)
        except Exception as exc:
            LOGGER.warning("Index setup warning: %s", exc)

    async def get_core_db(self) -> AsyncIOMotorDatabase:
        if not self._core_client:
            await self.connect()
        return self._core_client.get_database()

    async def get_active_media_db(self) -> tuple[AsyncIOMotorDatabase, str]:
        """Returns active DB shard and its identifier string."""
        async with self._lock:
            client = self._media_clients[self.active_db_index]
            db_name = f"DATABASE_{self.active_db_index + 2}"
            return client.get_database(), db_name

    async def get_db_usage_bytes(self, db: AsyncIOMotorDatabase) -> int:
        """Calculates dataSize + indexSize in bytes."""
        try:
            stats = await db.command("dbStats")
            return int(stats.get("dataSize", 0) + stats.get("indexSize", 0))
        except Exception:
            return 0

    async def _select_active_shard(self) -> None:
        for idx, client in enumerate(self._media_clients):
            db = client.get_database()
            usage = await self.get_db_usage_bytes(db)
            if usage < self.rotation_bytes:
                self.active_db_index = idx
                LOGGER.info("Active database shard DATABASE_%d (Usage: %.2f MB)", idx + 2, usage / (1024 * 1024))
                return
        self.active_db_index = len(self._media_clients) - 1
        LOGGER.warning("All shards exceed threshold. Set active shard to DATABASE_%d", self.active_db_index + 2)

    async def check_and_rotate(self) -> tuple[AsyncIOMotorDatabase, str]:
        """Rotates to next shard if current shard reaches 400 MB."""
        async with self._lock:
            client = self._media_clients[self.active_db_index]
            db = client.get_database()
            usage = await self.get_db_usage_bytes(db)

            if usage >= self.rotation_bytes and self.active_db_index < len(self._media_clients) - 1:
                old_idx = self.active_db_index + 2
                self.active_db_index += 1
                new_idx = self.active_db_index + 2
                LOGGER.info("🗄️ DATABASE_%d reached safe threshold. 🔄 Switching to DATABASE_%d", old_idx, new_idx)
                client = self._media_clients[self.active_db_index]
                db = client.get_database()

            return db, f"DATABASE_{self.active_db_index + 2}"

    async def find_in_all_shards(self, query: dict[str, Any], limit: int = 1) -> list[dict[str, Any]]:
        """Queries across all media database shards concurrently."""
        results: list[dict[str, Any]] = []

        async def _query_shard(client: AsyncIOMotorClient):
            db = client.get_database()
            return await db.media.find(query).limit(limit).to_list(length=limit)

        tasks = [_query_shard(client) for client in self._media_clients]
        shard_results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in shard_results:
            if isinstance(res, list) and res:
                results.extend(res)
                if len(results) >= limit:
                    break
        return results[:limit]
