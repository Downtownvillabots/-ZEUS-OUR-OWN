"""
Database Manager module handling search across core and sharded databases.
"""
from __future__ import annotations

import asyncio
from typing import Any
from motor.motor_asyncio import AsyncIOMotorClient
from app.logging import get_logger

LOGGER = get_logger(__name__)


class DatabaseManager:
    def __init__(
        self,
        core_uri: str,
        db_name: str = "Cluster0",
        media_uris: list[str] | None = None,
        rotation_mb: float = 400.0,
    ):
        self.core_uri = core_uri
        self.db_name = db_name
        self.media_uris = media_uris or []
        self.rotation_mb = rotation_mb

        self.core_client: AsyncIOMotorClient | None = None
        self.core_db = None
        self._media_clients: list[AsyncIOMotorClient] = []

    async def connect(self) -> None:
        """Asynchronously initializes database clients and connections."""
        LOGGER.info("INITIALIZING DATABASE MANAGER CONNECTIONS...")
        if self.core_uri:
            self.core_client = AsyncIOMotorClient(self.core_uri)
            self.core_db = self.core_client[self.db_name]
        
        self._media_clients = [AsyncIOMotorClient(uri) for uri in self.media_uris]
        LOGGER.info("DATABASE MANAGER CONNECTED SUCCESSFULLY")

    async def disconnect(self) -> None:
        """Closes all open database client connections."""
        if self.core_client:
            self.core_client.close()
        for client in self._media_clients:
            client.close()
        LOGGER.info("DATABASE MANAGER DISCONNECTED")

    async def find_in_all_shards(self, query: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        """Queries core DB and media shards concurrently for matching documents."""
        results: list[dict[str, Any]] = []

        async def _query_client(client: AsyncIOMotorClient, target_db_name: str):
            try:
                db = client[target_db_name]
                return await db.media.find(query).limit(limit).to_list(length=limit)
            except Exception as e:
                LOGGER.error(f"Error querying database {target_db_name}: {e}")
                return []

        tasks = []

        # 1. Query Primary Core Database & Fallback 'test'
        if self.core_client:
            tasks.append(_query_client(self.core_client, self.db_name))
            tasks.append(_query_client(self.core_client, "test"))

        # 2. Query Media Shard Databases
        for idx, client in enumerate(self._media_clients):
            tasks.append(_query_client(client, f"media_shard_{idx + 2}"))

        shard_results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_ids = set()
        for res in shard_results:
            if isinstance(res, list):
                for doc in res:
                    doc_id = str(doc.get("_id") or doc.get("file_unique_id"))
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        results.append(doc)

        return results[:limit]
