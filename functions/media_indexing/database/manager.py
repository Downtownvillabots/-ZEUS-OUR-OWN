"""
Database Manager module handling search across core and sharded databases.
"""
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
        self.db_name = db_name
        self.core_client = AsyncIOMotorClient(core_uri) if core_uri else None
        self.core_db = self.core_client[self.db_name] if self.core_client else None
        
        # Initialize media shard clients
        self.media_uris = media_uris or []
        self._media_clients = [AsyncIOMotorClient(uri) for uri in self.media_uris]
        self.rotation_mb = rotation_mb

    async def find_in_all_shards(self, query: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        """Queries the core DB and all media shards concurrently for matching documents."""
        results: list[dict[str, Any]] = []

        async def _query_client(client: AsyncIOMotorClient, target_db_name: str):
            try:
                db = client[target_db_name]
                # Target the 'media' collection explicitly
                return await db.media.find(query).limit(limit).to_list(length=limit)
            except Exception as e:
                LOGGER.error(f"Error querying {target_db_name}: {e}")
                return []

        tasks = []
        
        # 1. Query the main core database (e.g., Cluster0)
        if self.core_client:
            tasks.append(_query_client(self.core_client, self.db_name))
            # Fallback check for default 'test' collection if documents were indexed earlier
            tasks.append(_query_client(self.core_client, "test"))

        # 2. Query all configured media shard databases
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
