"""
File repository / indexing layer for the new Telegram bot.

Design goals:
- Keep Telegram/Pyrogram code out of the database layer.
- Store normalized file metadata in MongoDB.
- Preserve the useful behavior of the old bot's save_file() contract:
    (True, <id/code>) for a newly indexed file
    (False, 0) for a duplicate
    (False, 2) for a database/storage error
- Provide efficient search primitives for the search service.
- Be safe to call concurrently from multiple indexing workers.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Mapping, Optional, Sequence

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)

# Result codes retained for compatibility with the old indexing flow.
SAVE_OK = 1
SAVE_DUPLICATE = 0
SAVE_ERROR = 2


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_text(value: Any) -> str:
    """Normalize searchable text without destroying useful filename tokens."""
    if value is None:
        return ""
    value = str(value).replace("\x00", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_filename(filename: Any) -> str:
    filename = normalize_text(filename)
    # Telegram filenames can contain repeated separators; retain the original
    # filename separately, while making this field easier to search.
    return filename


def filename_stem(filename: str) -> str:
    filename = normalize_filename(filename)
    if not filename:
        return ""
    # Remove only the final extension.
    return re.sub(r"\.[A-Za-z0-9]{1,8}$", "", filename)


def filename_tokens(filename: str) -> list[str]:
    stem = filename_stem(filename).lower()
    tokens = re.findall(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", stem)
    return [t for t in tokens if t]


def normalize_file_type(file_type: Any) -> str:
    value = normalize_text(file_type).lower()
    aliases = {
        "document": "document",
        "video": "video",
        "audio": "audio",
        "photo": "photo",
        "animation": "animation",
    }
    return aliases.get(value, value or "document")


def make_file_key(
    file_id: str,
    file_unique_id: Optional[str] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
) -> str:
    """
    Create a stable deduplication key.

    Telegram's file_unique_id is preferable because it remains stable across
    messages. If unavailable, include the source message identity.
    """
    if file_unique_id:
        return f"tg:{file_unique_id}"

    if file_id:
        return f"tg-file:{file_id}"

    raw = f"{chat_id}:{message_id}"
    return "msg:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class FileRecord:
    file_id: str
    file_name: str
    file_size: int = 0
    file_type: str = "document"
    mime_type: Optional[str] = None
    caption: Optional[str] = None

    # Source Telegram message.
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    chat_username: Optional[str] = None
    chat_title: Optional[str] = None

    # Stable Telegram identifier used for deduplication.
    file_unique_id: Optional[str] = None

    # Search-oriented metadata.
    stem: str = ""
    tokens: list[str] = field(default_factory=list)
    normalized_name: str = ""

    # Optional media metadata.
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    performer: Optional[str] = None
    title: Optional[str] = None

    # Application metadata.
    indexed_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    source: str = "telegram"

    def __post_init__(self) -> None:
        self.file_id = normalize_text(self.file_id)
        self.file_name = normalize_filename(self.file_name)
        self.file_type = normalize_file_type(self.file_type)
        self.mime_type = normalize_text(self.mime_type) or None
        self.caption = normalize_text(self.caption) or None

        if not self.stem:
            self.stem = filename_stem(self.file_name)
        if not self.normalized_name:
            self.normalized_name = self.stem.lower()
        if not self.tokens:
            self.tokens = filename_tokens(self.file_name)

        self.file_size = max(0, int(self.file_size or 0))

    @property
    def key(self) -> str:
        return make_file_key(
            self.file_id,
            self.file_unique_id,
            self.chat_id,
            self.message_id,
        )

    def to_document(self) -> dict[str, Any]:
        data = asdict(self)
        data["_id"] = self.key
        return data

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "FileRecord":
        data = dict(document)
        data.pop("_id", None)
        return cls(**data)


class FileRepository:
    """
    MongoDB repository for indexed Telegram files.

    Expected collection:
        files

    Recommended indexes are created by ensure_indexes().
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        collection_name: str = "files",
    ) -> None:
        self.db = db
        self.collection: AsyncIOMotorCollection = db[collection_name]

    async def ensure_indexes(self) -> None:
        """Create indexes used by indexing, exact lookup and search."""
        await self.collection.create_index(
            [("file_unique_id", ASCENDING)],
            name="file_unique_id_unique",
            unique=True,
            sparse=True,
        )

        await self.collection.create_index(
            [("chat_id", ASCENDING), ("message_id", ASCENDING)],
            name="source_message",
            unique=True,
            sparse=True,
        )

        await self.collection.create_index(
            [("file_type", ASCENDING), ("file_size", DESCENDING)],
            name="type_size",
        )

        await self.collection.create_index(
            [("chat_id", ASCENDING), ("indexed_at", DESCENDING)],
            name="chat_indexed_at",
        )

        await self.collection.create_index(
            [("normalized_name", TEXT), ("caption", TEXT)],
            name="filename_text_search",
            default_language="english",
        )

        await self.collection.create_index(
            [("tokens", ASCENDING)],
            name="filename_tokens",
        )

        await self.collection.create_index(
            [("indexed_at", DESCENDING)],
            name="indexed_at",
        )

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------

    async def save_file(self, media: Any, **source: Any) -> tuple[bool, int]:
        """
        Compatibility implementation of the old save_file(media) helper.

        `media` may be a Pyrogram media object or a mapping containing the
        corresponding fields.
        """
        try:
            record = self.record_from_media(media, **source)
            return await self.insert(record)
        except DuplicateKeyError:
            return False, SAVE_DUPLICATE
        except Exception:
            logger.exception("Failed to save file")
            return False, SAVE_ERROR

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @staticmethod
    def record_from_media(
        media: Any,
        *,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        chat_username: Optional[str] = None,
        chat_title: Optional[str] = None,
        caption: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> FileRecord:
        """
        Convert a Pyrogram media object into the application's normalized
        FileRecord.
        """
        def read(name: str, default: Any = None) -> Any:
            if isinstance(media, Mapping):
                return media.get(name, default)
            return getattr(media, name, default)

        actual_file_type = file_type or read("file_type") or read("message_type")
        actual_file_type = normalize_file_type(actual_file_type)

        file_id = read("file_id", "") or ""
        file_unique_id = read("file_unique_id")

        return FileRecord(
            file_id=str(file_id),
            file_unique_id=file_unique_id,
            file_name=read("file_name", "") or read("file_name", "unknown"),
            file_size=read("file_size", 0) or 0,
            file_type=actual_file_type,
            mime_type=read("mime_type"),
            caption=caption if caption is not None else read("caption"),
            chat_id=chat_id,
            message_id=message_id,
            chat_username=chat_username,
            chat_title=chat_title,
            duration=read("duration"),
            width=read("width"),
            height=read("height"),
            performer=read("performer"),
            title=read("title"),
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def insert(self, record: FileRecord) -> tuple[bool, int]:
        """Insert one record; duplicate records return (False, 0)."""
        document = record.to_document()

        try:
            await self.collection.insert_one(document)
            return True, SAVE_OK
        except DuplicateKeyError:
            return False, SAVE_DUPLICATE
        except PyMongoError:
            logger.exception("MongoDB error while inserting file")
            return False, SAVE_ERROR

    async def upsert(self, record: FileRecord) -> tuple[bool, int]:
        """
        Idempotently insert/update a file.

        Returns:
            (True, SAVE_OK) when a new record is inserted.
            (False, SAVE_DUPLICATE) when an existing record was updated.
            (False, SAVE_ERROR) on failure.
        """
        try:
            document = record.to_document()
            key = document["_id"]
            document.pop("_id", None)

            result = await self.collection.update_one(
                {"_id": key},
                {
                    "$set": {**document, "updated_at": utcnow()},
                    "$setOnInsert": {"indexed_at": record.indexed_at},
                },
                upsert=True,
            )

            if result.upserted_id is not None:
                return True, SAVE_OK
            return False, SAVE_DUPLICATE
        except PyMongoError:
            logger.exception("MongoDB error while upserting file")
            return False, SAVE_ERROR

    async def bulk_insert(
        self,
        records: Iterable[FileRecord],
    ) -> dict[str, int]:
        """
        Bulk insert records.

        Duplicate files are ignored individually so one duplicate does not
        abort an indexing batch.
        """
        records = list(records)
        if not records:
            return {"saved": 0, "duplicates": 0, "errors": 0}

        saved = duplicates = errors = 0

        # unordered insert gives better throughput and lets MongoDB continue
        # after duplicate-key errors.
        from pymongo import InsertOne
        from pymongo.errors import BulkWriteError

        operations = [
            InsertOne(record.to_document())
            for record in records
        ]

        try:
            result = await self.collection.bulk_write(
                operations,
                ordered=False,
            )
            saved = result.inserted_count
            return {
                "saved": saved,
                "duplicates": 0,
                "errors": 0,
            }
        except BulkWriteError as exc:
            details = exc.details or {}
            saved = int(details.get("nInserted", 0))

            for error in details.get("writeErrors", []):
                if error.get("code") == 11000:
                    duplicates += 1
                else:
                    errors += 1

            return {
                "saved": saved,
                "duplicates": duplicates,
                "errors": errors,
            }
        except PyMongoError:
            logger.exception("Bulk insert failed")
            return {
                "saved": 0,
                "duplicates": 0,
                "errors": len(records),
            }

    async def delete(self, file_key: str) -> bool:
        result = await self.collection.delete_one({"_id": file_key})
        return result.deleted_count == 1

    async def delete_by_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> bool:
        result = await self.collection.delete_one(
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
            }
        )
        return result.deleted_count == 1

    async def delete_by_chat(self, chat_id: int) -> int:
        result = await self.collection.delete_many(
            {"chat_id": int(chat_id)}
        )
        return result.deleted_count

    async def delete_all(self) -> int:
        result = await self.collection.delete_many({})
        return result.deleted_count

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_by_key(self, file_key: str) -> Optional[FileRecord]:
        document = await self.collection.find_one({"_id": file_key})
        return FileRecord.from_document(document) if document else None

    async def get_by_file_unique_id(
        self,
        file_unique_id: str,
    ) -> Optional[FileRecord]:
        document = await self.collection.find_one(
            {"file_unique_id": file_unique_id}
        )
        return FileRecord.from_document(document) if document else None

    async def get_by_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> Optional[FileRecord]:
        document = await self.collection.find_one(
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
            }
        )
        return FileRecord.from_document(document) if document else None

    async def exists(
        self,
        *,
        file_unique_id: Optional[str] = None,
        file_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
    ) -> bool:
        query: dict[str, Any] = {}

        if file_unique_id:
            query["file_unique_id"] = file_unique_id
        elif file_id:
            query["file_id"] = file_id
        elif chat_id is not None and message_id is not None:
            query.update(
                {
                    "chat_id": int(chat_id),
                    "message_id": int(message_id),
                }
            )
        else:
            raise ValueError("A file identity is required")

        return await self.collection.find_one(
            query,
            projection={"_id": 1},
        ) is not None

    async def count(
        self,
        *,
        chat_id: Optional[int] = None,
        file_type: Optional[str] = None,
    ) -> int:
        query: dict[str, Any] = {}

        if chat_id is not None:
            query["chat_id"] = int(chat_id)
        if file_type:
            query["file_type"] = normalize_file_type(file_type)

        return await self.collection.count_documents(query)

    async def get_chat_count(self, chat_id: int) -> int:
        return await self.count(chat_id=chat_id)

    # ------------------------------------------------------------------
    # Search primitives
    # ------------------------------------------------------------------

    def _build_filter(
        self,
        *,
        chat_id: Optional[int] = None,
        file_types: Optional[Sequence[str]] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}

        if chat_id is not None:
            query["chat_id"] = int(chat_id)

        if file_types:
            query["file_type"] = {
                "$in": [normalize_file_type(x) for x in file_types]
            }

        if min_size is not None or max_size is not None:
            size_filter: dict[str, int] = {}
            if min_size is not None:
                size_filter["$gte"] = max(0, int(min_size))
            if max_size is not None:
                size_filter["$lte"] = max(0, int(max_size))
            query["file_size"] = size_filter

        return query

    async def search_text(
        self,
        query: str,
        *,
        chat_id: Optional[int] = None,
        limit: int = 30,
        skip: int = 0,
    ) -> list[FileRecord]:
        """
        MongoDB text-search primitive.

        The higher-level search service should normally tokenize and rank
        results further rather than exposing this method directly to users.
        """
        query = normalize_text(query)
        if not query:
            return []

        base = self._build_filter(chat_id=chat_id)
        base["$text"] = {"$search": query}

        cursor = (
            self.collection
            .find(
                base,
                projection={"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .skip(max(0, int(skip)))
            .limit(max(1, min(int(limit), 1000)))
        )

        return [
            FileRecord.from_document(doc)
            async for doc in cursor
        ]

    async def search_regex(
        self,
        pattern: str,
        *,
        chat_id: Optional[int] = None,
        limit: int = 30,
    ) -> list[FileRecord]:
        """
        Regex fallback for exact phrase/pattern searches.

        Use sparingly on large collections; the search service should prefer
        text/token indexes first.
        """
        if not pattern:
            return []

        base = self._build_filter(chat_id=chat_id)
        base["file_name"] = {
            "$regex": pattern,
            "$options": "i",
        }

        cursor = (
            self.collection
            .find(base)
            .sort("indexed_at", DESCENDING)
            .limit(max(1, min(int(limit), 1000)))
        )

        return [
            FileRecord.from_document(doc)
            async for doc in cursor
        ]

    async def search_tokens(
        self,
        tokens: Sequence[str],
        *,
        chat_id: Optional[int] = None,
        limit: int = 30,
    ) -> list[FileRecord]:
        clean = [
            normalize_text(token).lower()
            for token in tokens
            if normalize_text(token)
        ]
        if not clean:
            return []

        base = self._build_filter(chat_id=chat_id)
        base["tokens"] = {"$all": clean}

        cursor = (
            self.collection
            .find(base)
            .sort("indexed_at", DESCENDING)
            .limit(max(1, min(int(limit), 1000)))
        )

        return [
            FileRecord.from_document(doc)
            async for doc in cursor
        ]

    async def recent(
        self,
        *,
        chat_id: Optional[int] = None,
        limit: int = 30,
    ) -> list[FileRecord]:
        query = self._build_filter(chat_id=chat_id)
        cursor = (
            self.collection
            .find(query)
            .sort("indexed_at", DESCENDING)
            .limit(max(1, min(int(limit), 1000)))
        )
        return [
            FileRecord.from_document(doc)
            async for doc in cursor
        ]

    async def iter_chat(
        self,
        chat_id: int,
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[FileRecord]:
        cursor = (
            self.collection
            .find({"chat_id": int(chat_id)})
            .sort("message_id", ASCENDING)
            .batch_size(max(1, int(batch_size)))
        )

        async for document in cursor:
            yield FileRecord.from_document(document)

    # ------------------------------------------------------------------
    # Statistics / maintenance
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        total = await self.collection.count_documents({})

        pipeline = [
            {
                "$group": {
                    "_id": "$file_type",
                    "count": {"$sum": 1},
                    "bytes": {"$sum": "$file_size"},
                }
            },
            {"$sort": {"count": -1}},
        ]

        by_type: dict[str, dict[str, int]] = {}
        async for row in self.collection.aggregate(pipeline):
            by_type[str(row["_id"])] = {
                "count": int(row.get("count", 0)),
                "bytes": int(row.get("bytes", 0)),
            }

        return {
            "total": total,
            "by_type": by_type,
        }

    async def get_database_size(self) -> int:
        stats = await self.db.command("dbStats")
        return int(stats.get("dataSize", 0))

    async def prune_missing_sources(
        self,
        valid_message_keys: set[tuple[int, int]],
        *,
        chat_id: Optional[int] = None,
    ) -> int:
        """
        Remove records whose source messages are no longer known.

        This is intentionally explicit: the repository never calls Telegram
        to determine whether a message still exists.
        """
        query: dict[str, Any] = {
            "chat_id": int(chat_id) if chat_id is not None else {"$exists": True}
        }

        stale_ids: list[Any] = []
        cursor = self.collection.find(
            query,
            projection={"_id": 1, "chat_id": 1, "message_id": 1},
        )

        async for doc in cursor:
            key = (doc.get("chat_id"), doc.get("message_id"))
            if key not in valid_message_keys:
                stale_ids.append(doc["_id"])

        if not stale_ids:
            return 0

        result = await self.collection.delete_many(
            {"_id": {"$in": stale_ids}}
        )
        return result.deleted_count


# ----------------------------------------------------------------------
# Standalone helper functions
# ----------------------------------------------------------------------

def record_from_pyrogram_message(message: Any) -> Optional[FileRecord]:
    """
    Extract supported media from a Pyrogram Message.

    Supported media:
        video, audio, document

    The old bot indexed these three media types. Photos, stickers, voices,
    animations, etc. can be added later without changing the repository API.
    """
    if not message or getattr(message, "empty", False):
        return None

    media_type = getattr(message, "media", None)
    if media_type is None:
        return None

    media_name = getattr(media_type, "value", str(media_type))

    if media_name not in {"video", "audio", "document"}:
        return None

    media = getattr(message, media_name, None)
    if not media:
        return None

    chat = getattr(message, "chat", None)

    return FileRepository.record_from_media(
        media,
        chat_id=getattr(chat, "id", None),
        message_id=getattr(message, "id", None),
        chat_username=getattr(chat, "username", None),
        chat_title=getattr(chat, "title", None),
        caption=getattr(message, "caption", None),
        file_type=media_name,
    )


def extract_searchable_name(record: FileRecord) -> str:
    """Return the canonical name used by the search/ranking service."""
    return record.normalized_name or filename_stem(record.file_name).lower()


def is_supported_media(message: Any) -> bool:
    return record_from_pyrogram_message(message) is not None


async def save_file(
    collection_or_repository: Any,
    media: Any,
    **source: Any,
) -> tuple[bool, int]:
    """
    Compatibility facade.

    Accepts either:
        save_file(FileRepository(...), media)
    or:
        save_file(motor_collection, media)

    The repository form is preferred.
    """
    if isinstance(collection_or_repository, FileRepository):
        return await collection_or_repository.save_file(media, **source)

    # Lightweight collection compatibility for projects that still import
    # save_file() directly while migrating to FileRepository.
    collection = collection_or_repository
    record = FileRepository.record_from_media(media, **source)

    try:
        await collection.insert_one(record.to_document())
        return True, SAVE_OK
    except DuplicateKeyError:
        return False, SAVE_DUPLICATE
    except Exception:
        logger.exception("Compatibility save_file failed")
        return False, SAVE_ERROR


__all__ = [
    "SAVE_OK",
    "SAVE_DUPLICATE",
    "SAVE_ERROR",
    "FileRecord",
    "FileRepository",
    "filename_stem",
    "filename_tokens",
    "make_file_key",
    "normalize_filename",
    "normalize_text",
    "record_from_pyrogram_message",
    "extract_searchable_name",
    "is_supported_media",
    "save_file",
]
