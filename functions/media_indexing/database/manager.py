"""MongoDB media database rotation and collection management."""
from __future__ import annotations
import time
from dataclasses import dataclass

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:  # Allows the rest of the bot to import without Motor.
    AsyncIOMotorClient = None


@dataclass(slots=True)
class MediaDatabase:
    number: int
    uri: str
    client: object
    database: object
    collection: object


class MongoMediaManager:
    """Manages Database 2+ and rotates before the configured safe threshold."""

    def __init__(self, uris: tuple[str, ...], rotation_mb: int = 400):
        if not uris:
            raise ValueError("MEDIA_DATABASE_URIS is empty")
        if AsyncIOMotorClient is None:
            raise RuntimeError(
                "Motor is required for MongoDB media indexing. Add motor to requirements.txt."
            )
        self.uris = uris
        self.rotation_bytes = rotation_mb * 1024 * 1024
        self.databases: list[MediaDatabase] = []
        self.active_index = 0

    async def connect(self) -> None:
        for offset, uri in enumerate(self.uris, start=2):
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            await client.admin.command("ping")
            db = client[f"downtown_villa_database_{offset}"]
            collection = db["media"]
            await self._ensure_indexes(collection)
            self.databases.append(MediaDatabase(offset, uri, client, db, collection))

    async def _ensure_indexes(self, collection) -> None:
        await collection.create_index("file_unique_id", sparse=True)
        await collection.create_index([("normalized_title", 1), ("file_size", 1)])
        await collection.create_index(
            [("normalized_title", 1), ("year", 1), ("season", 1), ("episode", 1)]
        )
        await collection.create_index("source_message_id")

    async def _storage_bytes(self, database) -> int:
        stats = await database.command("dbStats")
        return int(stats.get("dataSize", 0)) + int(stats.get("indexSize", 0))

    async def writable(self) -> MediaDatabase:
        for index, target in enumerate(self.databases):
            used = await self._storage_bytes(target.database)
            if used < self.rotation_bytes:
                self.active_index = index
                return target
        raise RuntimeError("All media databases reached the configured safe threshold")

    async def close(self) -> None:
        for item in self.databases:
            item.client.close()
