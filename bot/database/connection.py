"""
bot.database.connection
DOWNTOWN VILLA BOT — Ultimate MongoDB Database Layer

This file is intentionally self-contained.

ARCHITECTURE
============
MONGO_URI
    Core database:
      users, groups, premium, verification, referrals, settings,
      bot_state, media_locations, shard_registry, shard_monitoring,
      movie_catalog, series_catalog, episodes, and other lightweight
      application state.

MONGO_URI_2, MONGO_URI_3, ...
    Media metadata shards:
      media_files only (Telegram file metadata, never media bytes).

IMPORTANT
=========
The application server must not permanently store movie/series bytes.
Telegram owns the actual media. MongoDB stores Telegram identifiers and
lightweight searchable metadata.

Shard rules:
* Core is shard #1 and is never a media write shard.
* Media shards start at #2.
* New media records use the first healthy shard below its configured
  safety threshold.
* Existing records never move automatically.
* media_id is the stable internal identity.
* telegram_file_id is indexed for duplicate protection.
* media_locations in core is the authoritative routing registry.
* A failed shard is removed from new writes but remains readable when
  possible and is periodically retried.
* There is no application-imposed practical shard count other than the
  environment's ability to define MONGO_URI_N variables.

This module also exposes legacy user/group/file methods used by older
DOWNTOWN VILLA BOT handlers so callers can migrate incrementally.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Optional

from pymongo import (
    ASCENDING,
    DESCENDING,
    AsyncMongoClient,
)
from pymongo.errors import (
    BulkWriteError,
    ConnectionFailure,
    DuplicateKeyError,
    NetworkTimeout,
    PyMongoError,
    ServerSelectionTimeoutError,
)

logger = logging.getLogger(__name__)

CORE_SHARD_ID = "core"
CORE_DATABASE_DEFAULT = "telegram_bot"
DEFAULT_APP_NAME = "downtown-villa-bot"
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 10_000
DEFAULT_CONNECT_TIMEOUT_MS = 10_000
DEFAULT_SOCKET_TIMEOUT_MS = 30_000
DEFAULT_MONITOR_INTERVAL_SECONDS = 60
DEFAULT_HEALTH_RETRY_SECONDS = 30
DEFAULT_SHARD_LIMIT_MB = 450
DEFAULT_THRESHOLD_PERCENT = 85.0
DEFAULT_MAX_SHARD_NUMBER = 10_000_000

USERS = "users"
GROUPS = "groups"
PREMIUM = "premium"
VERIFICATION = "verification"
REFERRALS = "referrals"
SETTINGS = "settings"
BOT_STATE = "bot_state"
MEDIA_LOCATIONS = "media_locations"
SHARD_REGISTRY = "shard_registry"
SHARD_MONITORING = "shard_monitoring"
MOVIE_CATALOG = "movie_catalog"
SERIES_CATALOG = "series_catalog"
EPISODES = "episodes"
MEDIA_FILES = "media_files"
REQUESTS = "requests"
LOGS = "logs"
ANALYTICS = "analytics"

SHARD_URI_PATTERN = re.compile(r"^MONGO_URI_(\d+)$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def sanitize_uri(uri: str) -> str:
    if not uri:
        return "<not-configured>"
    try:
        scheme, remainder = str(uri).split("://", 1)
        if "@" not in remainder:
            return f"{scheme}://{remainder}"
        credentials, host = remainder.split("@", 1)
        username = credentials.split(":", 1)[0]
        return f"{scheme}://{username}:***@{host}"
    except Exception:
        return "<redacted>"


@dataclass
class MediaShardConfig:
    shard_id: str
    number: int
    uri: str
    database: str
    limit_mb: int = DEFAULT_SHARD_LIMIT_MB
    threshold_percent: float = DEFAULT_THRESHOLD_PERCENT
    server_selection_timeout_ms: int = DEFAULT_SERVER_SELECTION_TIMEOUT_MS
    connect_timeout_ms: int = DEFAULT_CONNECT_TIMEOUT_MS
    socket_timeout_ms: int = DEFAULT_SOCKET_TIMEOUT_MS
    application_name: str = DEFAULT_APP_NAME
    enabled: bool = True

    @property
    def limit_bytes(self) -> int:
        return max(1, self.limit_mb) * 1024 * 1024

    @property
    def threshold_bytes(self) -> int:
        return int(self.limit_bytes * self.threshold_percent / 100.0)

    def sanitized_uri(self) -> str:
        return sanitize_uri(self.uri)


@dataclass
class DatabaseConfig:
    uri: str = ""
    database: str = CORE_DATABASE_DEFAULT
    server_selection_timeout_ms: int = DEFAULT_SERVER_SELECTION_TIMEOUT_MS
    connect_timeout_ms: int = DEFAULT_CONNECT_TIMEOUT_MS
    socket_timeout_ms: int = DEFAULT_SOCKET_TIMEOUT_MS
    application_name: str = DEFAULT_APP_NAME
    monitor_interval_seconds: int = DEFAULT_MONITOR_INTERVAL_SECONDS
    recovery_retry_seconds: int = DEFAULT_HEALTH_RETRY_SECONDS
    shards: list[MediaShardConfig] = field(default_factory=list)

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        result = cls(
            uri=(os.getenv("MONGO_URI") or os.getenv("MONGODB_URI") or "").strip(),
            database=(os.getenv("MONGO_DATABASE") or os.getenv("MONGODB_DATABASE") or CORE_DATABASE_DEFAULT).strip(),
            server_selection_timeout_ms=_safe_int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS"), DEFAULT_SERVER_SELECTION_TIMEOUT_MS),
            connect_timeout_ms=_safe_int(os.getenv("MONGO_CONNECT_TIMEOUT_MS"), DEFAULT_CONNECT_TIMEOUT_MS),
            socket_timeout_ms=_safe_int(os.getenv("MONGO_SOCKET_TIMEOUT_MS"), DEFAULT_SOCKET_TIMEOUT_MS),
            application_name=(os.getenv("MONGO_APP_NAME") or DEFAULT_APP_NAME).strip(),
            monitor_interval_seconds=_safe_int(os.getenv("MONGO_MONITOR_INTERVAL_SECONDS"), DEFAULT_MONITOR_INTERVAL_SECONDS),
            recovery_retry_seconds=_safe_int(os.getenv("MONGO_RECOVERY_RETRY_SECONDS"), DEFAULT_HEALTH_RETRY_SECONDS),
        )
        result.shards = _discover_media_shards(result)
        return result

    @classmethod
    def from_config(cls, config: Any) -> "DatabaseConfig":
        if config is None:
            return cls.from_environment()
        if isinstance(config, cls):
            return config
        getter = config.get if isinstance(config, dict) else lambda k, d=None: getattr(config, k, d)
        result = cls(
            uri=str(getter("mongo_uri", getter("mongodb_uri", getter("database_uri", getter("uri", os.getenv("MONGO_URI", "")))))).strip(),
            database=str(getter("mongo_database", getter("database", os.getenv("MONGO_DATABASE", CORE_DATABASE_DEFAULT)))).strip(),
            server_selection_timeout_ms=_safe_int(getter("mongo_server_selection_timeout_ms", os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS")), DEFAULT_SERVER_SELECTION_TIMEOUT_MS),
            connect_timeout_ms=_safe_int(getter("mongo_connect_timeout_ms", os.getenv("MONGO_CONNECT_TIMEOUT_MS")), DEFAULT_CONNECT_TIMEOUT_MS),
            socket_timeout_ms=_safe_int(getter("mongo_socket_timeout_ms", os.getenv("MONGO_SOCKET_TIMEOUT_MS")), DEFAULT_SOCKET_TIMEOUT_MS),
            application_name=str(getter("mongo_app_name", os.getenv("MONGO_APP_NAME", DEFAULT_APP_NAME))),
            monitor_interval_seconds=_safe_int(getter("mongo_monitor_interval_seconds", os.getenv("MONGO_MONITOR_INTERVAL_SECONDS")), DEFAULT_MONITOR_INTERVAL_SECONDS),
            recovery_retry_seconds=_safe_int(getter("mongo_recovery_retry_seconds", os.getenv("mongo_recovery_retry_seconds", os.getenv("MONGO_RECOVERY_RETRY_SECONDS"))), DEFAULT_HEALTH_RETRY_SECONDS),
        )
        result.shards = _discover_media_shards(result)
        return result

    def validate(self) -> None:
        if not self.uri:
            raise RuntimeError("MONGO_URI is not configured.")
        if not self.database:
            raise RuntimeError("MONGO_DATABASE is not configured.")
        seen: set[str] = set()
        for shard in self.shards:
            if shard.shard_id in seen:
                raise RuntimeError(f"Duplicate media shard: {shard.shard_id}")
            seen.add(shard.shard_id)
            if not shard.uri:
                raise RuntimeError(f"{shard.shard_id} has no URI.")
            if shard.limit_mb <= 0:
                raise RuntimeError(f"{shard.shard_id} has invalid capacity.")
            if not 0 < shard.threshold_percent <= 100:
                raise RuntimeError(f"{shard.shard_id} has invalid threshold.")

    def sanitized_uri(self) -> str:
        return sanitize_uri(self.uri)

    def sanitized_url(self) -> str:
        return self.sanitized_uri()


def _discover_media_shards(config: DatabaseConfig) -> list[MediaShardConfig]:
    numbers = []
    for key, value in os.environ.items():
        match = SHARD_URI_PATTERN.match(key)
        if match and value.strip():
            number = int(match.group(1))
            if number >= 2 and number <= DEFAULT_MAX_SHARD_NUMBER:
                numbers.append(number)
    discovered = []
    for number in sorted(set(numbers)):
        uri = os.getenv(f"MONGO_URI_{number}", "").strip()
        if not uri:
            continue
        discovered.append(MediaShardConfig(
            shard_id=f"media_{number}",
            number=number,
            uri=uri,
            database=(os.getenv(f"MONGO_DATABASE_{number}") or f"downtown_media_{number:02d}").strip(),
            limit_mb=_safe_int(os.getenv(f"MONGO_SHARD_{number}_LIMIT_MB"), DEFAULT_SHARD_LIMIT_MB),
            threshold_percent=_safe_float(os.getenv(f"MONGO_SHARD_{number}_THRESHOLD_PERCENT"), DEFAULT_THRESHOLD_PERCENT),
            server_selection_timeout_ms=_safe_int(os.getenv(f"MONGO_SHARD_{number}_SERVER_SELECTION_TIMEOUT_MS"), config.server_selection_timeout_ms),
            connect_timeout_ms=_safe_int(os.getenv(f"MONGO_SHARD_{number}_CONNECT_TIMEOUT_MS"), config.connect_timeout_ms),
            socket_timeout_ms=_safe_int(os.getenv(f"MONGO_SHARD_{number}_SOCKET_TIMEOUT_MS"), config.socket_timeout_ms),
            application_name=f"{config.application_name}-media-{number}",
            enabled=_safe_bool(os.getenv(f"MONGO_SHARD_{number}_ENABLED"), True),
        ))
    return discovered


@dataclass
class ShardRuntime:
    config: MediaShardConfig
    client: Optional[AsyncMongoClient] = None
    database: Any = None
    healthy: bool = False
    accepting_writes: bool = False
    recovering: bool = False
    logical_size_bytes: int = 0
    document_count: int = 0
    reads: int = 0
    writes: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_capacity_check: Optional[datetime] = None
    failure_reason: Optional[str] = None
    recovery_attempts: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def shard_id(self) -> str:
        return self.config.shard_id

    @property
    def threshold_bytes(self) -> int:
        return self.config.threshold_bytes

    @property
    def utilization_percent(self) -> float:
        if self.config.limit_bytes <= 0:
            return 100.0
        return self.logical_size_bytes / self.config.limit_bytes * 100.0

    @property
    def threshold_reached(self) -> bool:
        return self.logical_size_bytes >= self.threshold_bytes

    @property
    def available_for_writes(self) -> bool:
        return self.healthy and self.accepting_writes and self.config.enabled and not self.threshold_reached


class DatabaseManager:
    """
    Central MongoDB manager.

    The class intentionally contains both modern APIs and legacy compatibility
    APIs. Existing handlers can therefore continue calling db.is_user_exist(),
    db.get_user(), db.get_ban_status(), etc., while newer services can use the
    structured methods below.
    """

    def __init__(self, config: Optional[DatabaseConfig] = None) -> None:
        self.config = config or DatabaseConfig.from_environment()
        self.client: Optional[AsyncMongoClient] = None
        self.database: Any = None
        self.initialized = False
        self._shards: dict[str, ShardRuntime] = {}
        self._active_write_shard: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._monitor_lock = asyncio.Lock()
        self._metrics = {
            "reads": 0,
            "writes": 0,
            "errors": 0,
            "started_at": None,
        }
        self._ensure_aliases()

    def _ensure_aliases(self) -> None:
        self.users_collection_name = USERS
        self.groups_collection_name = GROUPS
        self.media_collection_name = MEDIA_FILES

    @property
    def users(self):
        return self.collection(USERS)

    @property
    def groups(self):
        return self.collection(GROUPS)

    @property
    def premium(self):
        return self.collection(PREMIUM)

    @property
    def verification(self):
        return self.collection(VERIFICATION)

    @property
    def settings(self):
        return self.collection(SETTINGS)

    @property
    def media_locations(self):
        return self.collection(MEDIA_LOCATIONS)

    def create_client(self) -> AsyncMongoClient:
        if self.client is not None:
            return self.client
        self.config.validate()
        self.client = AsyncMongoClient(
            self.config.uri,
            serverSelectionTimeoutMS=self.config.server_selection_timeout_ms,
            connectTimeoutMS=self.config.connect_timeout_ms,
            socketTimeoutMS=self.config.socket_timeout_ms,
            appname=self.config.application_name,
        )
        self.database = self.client[self.config.database]
        logger.info("Core MongoDB client created: %s", self.config.sanitized_uri())
        logger.info("Core MongoDB database selected: %s", self.config.database)
        return self.client

    def get_database(self):
        if self.database is None:
            self.create_client()
        return self.database

    def collection(self, name: str):
        name = str(name).strip()
        if not name:
            raise ValueError("Collection name cannot be empty.")
        return self.get_database()[name]

    def core_collection(self, name: str):
        return self.collection(name)

    async def initialize(self) -> "DatabaseManager":
        if self.initialized:
            return self
        self.create_client()
        await self.health_check(raise_on_error=True)
        await self.initialize_indexes()
        await self.initialize_media_shards()
        self._metrics["started_at"] = utcnow()
        self.initialized = True
        await self.refresh_all_monitoring()
        await self.refresh_active_write_shard()
        self._start_monitor_task()
        logger.info(
            "MongoDB architecture initialized. Core=%s MediaShards=%d ActiveWriteShard=%s",
            self.config.database, len(self._shards), self._active_write_shard,
        )
        return self

    async def init_database(self) -> "DatabaseManager":
        return await self.initialize()

    async def health_check(self, *, raise_on_error: bool = False) -> bool:
        try:
            client = self.create_client()
            started = time.perf_counter()
            await client.admin.command("ping")
            self._metrics["reads"] += 1
            logger.debug("Core MongoDB ping %.2f ms", (time.perf_counter() - started) * 1000)
            return True
        except Exception:
            self._metrics["errors"] += 1
            if raise_on_error:
                raise
            logger.exception("Core MongoDB health check failed.")
            return False

    async def ping(self) -> bool:
        return await self.health_check()

    async def is_healthy(self) -> bool:
        return await self.health_check()

    async def initialize_indexes(self) -> None:
        indexes = [
            (USERS, [("user_id", ASCENDING)], {"unique": True, "name": "users_user_id_unique"}),
            (GROUPS, [("chat_id", ASCENDING)], {"unique": True, "name": "groups_chat_id_unique"}),
            (PREMIUM, [("user_id", ASCENDING)], {"unique": True, "name": "premium_user_id_unique"}),
            (VERIFICATION, [("user_id", ASCENDING)], {"unique": True, "name": "verification_user_id_unique"}),
            (REFERRALS, [("user_id", ASCENDING)], {"unique": True, "name": "referrals_user_id_unique"}),
            (MEDIA_LOCATIONS, [("media_id", ASCENDING)], {"unique": True, "name": "media_location_media_id_unique"}),
            (MEDIA_LOCATIONS, [("telegram_file_id", ASCENDING)], {"unique": True, "name": "media_location_file_id_unique", "sparse": True}),
            (SHARD_REGISTRY, [("shard_id", ASCENDING)], {"unique": True, "name": "shard_registry_shard_id_unique"}),
            (MOVIE_CATALOG, [("movie_id", ASCENDING)], {"unique": True, "name": "movie_id_unique"}),
            (SERIES_CATALOG, [("series_id", ASCENDING)], {"unique": True, "name": "series_id_unique"}),
            (EPISODES, [("episode_id", ASCENDING)], {"unique": True, "name": "episode_id_unique"}),
        ]
        for name, keys, options in indexes:
            try:
                await self.collection(name).create_index(keys, **options)
            except Exception:
                logger.exception("Unable to initialize core index %s", name)

    async def initialize_media_shards(self) -> None:
        for shard_config in self.config.shards:
            runtime = ShardRuntime(config=shard_config)
            self._shards[shard_config.shard_id] = runtime
            if shard_config.enabled:
                await self._connect_shard(runtime)
        await self._persist_shard_registry()

    async def _connect_shard(self, runtime: ShardRuntime) -> bool:
        async with runtime.lock:
            try:
                if runtime.client is None:
                    runtime.client = AsyncMongoClient(
                        runtime.config.uri,
                        serverSelectionTimeoutMS=runtime.config.server_selection_timeout_ms,
                        connectTimeoutMS=runtime.config.connect_timeout_ms,
                        socketTimeoutMS=runtime.config.socket_timeout_ms,
                        appname=runtime.config.application_name,
                    )
                    runtime.database = runtime.client[runtime.config.database]
                await runtime.client.admin.command("ping")
                runtime.healthy = True
                runtime.recovering = False
                runtime.accepting_writes = True
                runtime.last_success = utcnow()
                runtime.failure_reason = None
                await self._initialize_media_indexes(runtime)
                return True
            except Exception as exc:
                runtime.healthy = False
                runtime.accepting_writes = False
                runtime.recovering = True
                runtime.last_failure = utcnow()
                runtime.failure_reason = str(exc)
                runtime.recovery_attempts += 1
                runtime.errors += 1
                self._metrics["errors"] += 1
                logger.warning("Media shard %s unavailable: %s", runtime.shard_id, exc)
                return False

    async def _initialize_media_indexes(self, runtime: ShardRuntime) -> None:
        collection = runtime.database[MEDIA_FILES]
        indexes = [
            ([("media_id", ASCENDING)], {"unique": True, "name": "media_id_unique"}),
            ([("telegram_file_id", ASCENDING)], {"unique": True, "name": "telegram_file_id_unique"}),
            ([("movie_id", ASCENDING), ("created_at", DESCENDING)], {"name": "movie_created"}),
            ([("series_id", ASCENDING), ("episode_id", ASCENDING), ("created_at", DESCENDING)], {"name": "episode_created"}),
            ([("filename", ASCENDING)], {"name": "filename_index"}),
            ([("quality", ASCENDING)], {"name": "quality_index"}),
            ([("language", ASCENDING)], {"name": "language_index"}),
            ([("created_at", DESCENDING), ("media_id", DESCENDING)], {"name": "global_cursor_index"}),
        ]
        for keys, options in indexes:
            try:
                await collection.create_index(keys, **options)
            except Exception:
                logger.exception("Unable to initialize media index %s", options.get("name"))

    def shard(self, shard_id: str) -> ShardRuntime:
        runtime = self._shards.get(str(shard_id))
        if runtime is None:
            raise KeyError(f"Unknown media shard: {shard_id}")
        return runtime

    def shard_database(self, shard_id: str):
        return self.shard(shard_id).database

    def shard_collection(self, shard_id: str, name: str = MEDIA_FILES):
        runtime = self.shard(shard_id)
        if runtime.database is None:
            raise RuntimeError(f"Media shard {shard_id} is not connected.")
        return runtime.database[name]

    async def refresh_shard_capacity(self, runtime: ShardRuntime) -> dict[str, Any]:
        if runtime.database is None:
            return {}
        started = time.perf_counter()
        try:
            stats = await runtime.database.command("collStats", MEDIA_FILES)
            runtime.logical_size_bytes = int(stats.get("size", stats.get("storageSize", 0)) or 0)
            runtime.document_count = int(stats.get("count", 0) or 0)
            runtime.last_capacity_check = utcnow()
            runtime.last_latency_ms = (time.perf_counter() - started) * 1000
            runtime.total_latency_ms += runtime.last_latency_ms
            runtime.healthy = True
            runtime.last_success = utcnow()
            runtime.accepting_writes = not runtime.threshold_reached
            if runtime.threshold_reached:
                logger.warning("Media shard %s reached %.2f%% capacity.", runtime.shard_id, runtime.utilization_percent)
            return stats
        except Exception as exc:
            runtime.errors += 1
            self._metrics["errors"] += 1
            runtime.healthy = False
            runtime.accepting_writes = False
            runtime.recovering = True
            runtime.last_failure = utcnow()
            runtime.failure_reason = str(exc)
            return {}

    async def refresh_active_write_shard(self) -> Optional[str]:
        async with self._monitor_lock:
            candidates = [s for s in self._shards.values() if s.available_for_writes]
            candidates.sort(key=lambda s: (s.config.number, s.logical_size_bytes))
            self._active_write_shard = candidates[0].shard_id if candidates else None
            return self._active_write_shard

    def active_write_shard(self) -> Optional[str]:
        return self._active_write_shard

    async def get_write_shard(self) -> ShardRuntime:
        await self.refresh_all_monitoring()
        await self.refresh_active_write_shard()
        if self._active_write_shard:
            return self._shards[self._active_write_shard]
        for runtime in sorted(self._shards.values(), key=lambda x: x.config.number):
            if runtime.config.enabled and await self._connect_shard(runtime):
                await self.refresh_shard_capacity(runtime)
                if runtime.available_for_writes:
                    await self.refresh_active_write_shard()
                    return runtime
        raise RuntimeError("No healthy media MongoDB shard is currently available for writes.")

    @staticmethod
    def new_media_id() -> str:
        return uuid.uuid4().hex

    async def insert_media(self, document: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise TypeError("media document must be a dict")
        telegram_file_id = document.get("telegram_file_id") or document.get("file_id")
        if not telegram_file_id:
            raise ValueError("telegram_file_id is required")
        existing = await self.get_media_by_file_id(str(telegram_file_id))
        if existing:
            return await self.get_media(existing["media_id"]) or existing
        runtime = await self.get_write_shard()
        media_id = str(document.get("media_id") or self.new_media_id())
        record = dict(document)
        record["media_id"] = media_id
        record["telegram_file_id"] = str(telegram_file_id)
        record.setdefault("created_at", utcnow())
        record.setdefault("updated_at", utcnow())
        record.setdefault("schema_version", 1)
        try:
            result = await self.shard_collection(runtime.shard_id).insert_one(record)
            record["_id"] = result.inserted_id
            await self.media_locations.update_one(
                {"media_id": media_id},
                {"$set": {
                    "media_id": media_id,
                    "telegram_file_id": str(telegram_file_id),
                    "shard_id": runtime.shard_id,
                    "database_name": runtime.config.database,
                    "collection_name": MEDIA_FILES,
                    "status": "active",
                    "created_at": record["created_at"],
                    "updated_at": record["updated_at"],
                }},
                upsert=True,
            )
            runtime.writes += 1
            self._metrics["writes"] += 1
            await self.refresh_shard_capacity(runtime)
            await self.refresh_active_write_shard()
            return record
        except DuplicateKeyError:
            existing = await self.get_media_by_file_id(str(telegram_file_id))
            if existing:
                return await self.get_media(existing["media_id"]) or existing
            raise
        except Exception as exc:
            runtime.errors += 1
            self._metrics["errors"] += 1
            runtime.healthy = False
            runtime.accepting_writes = False
            runtime.recovering = True
            runtime.last_failure = utcnow()
            runtime.failure_reason = str(exc)
            raise

    async def upsert_media(self, document: dict[str, Any]) -> dict[str, Any]:
        file_id = document.get("telegram_file_id") or document.get("file_id")
        if not file_id:
            raise ValueError("telegram_file_id is required")
        existing = await self.get_media_by_file_id(str(file_id))
        if existing:
            return await self.update_media(existing["media_id"], document) or existing
        return await self.insert_media(document)

    async def get_media_location(self, media_id: str) -> Optional[dict[str, Any]]:
        self._metrics["reads"] += 1
        return await self.media_locations.find_one({"media_id": str(media_id)})

    async def get_media_by_file_id(self, telegram_file_id: str) -> Optional[dict[str, Any]]:
        self._metrics["reads"] += 1
        return await self.media_locations.find_one({"telegram_file_id": str(telegram_file_id), "status": {"$ne": "deleted"}})

    async def get_media(self, media_id: str) -> Optional[dict[str, Any]]:
        location = await self.get_media_location(media_id)
        if not location:
            return None
        runtime = self._shards.get(location["shard_id"])
        if runtime is None or runtime.database is None:
            return None
        self._metrics["reads"] += 1
        runtime.reads += 1
        return await self.shard_collection(location["shard_id"]).find_one({"media_id": str(media_id)})

    async def update_media(self, media_id: str, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
        location = await self.get_media_location(media_id)
        if not location:
            return None
        update = dict(fields)
        update.pop("_id", None)
        update["updated_at"] = utcnow()
        result = await self.shard_collection(location["shard_id"]).update_one({"media_id": str(media_id)}, {"$set": update})
        if not result.matched_count:
            return None
        return await self.get_media(media_id)

    async def delete_media(self, media_id: str) -> bool:
        location = await self.get_media_location(media_id)
        if not location:
            return False
        result = await self.shard_collection(location["shard_id"]).delete_one({"media_id": str(media_id)})
        if result.deleted_count:
            await self.media_locations.update_one({"media_id": str(media_id)}, {"$set": {"status": "deleted", "updated_at": utcnow()}})
            return True
        return False

    async def search_media_shard(self, shard_id: str, query: dict[str, Any], *, limit: int = 50, sort: Optional[list[tuple[str, int]]] = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        cursor = self.shard_collection(shard_id).find(query)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.limit(limit).to_list(length=limit)

    async def search_media(self, query: Optional[dict[str, Any]] = None, *, limit: int = 50) -> list[dict[str, Any]]:
        query = query or {}
        limit = max(1, min(int(limit), 500))
        per_shard = max(1, min(limit, 100))
        results: list[dict[str, Any]] = []
        for runtime in sorted(self._shards.values(), key=lambda x: x.config.number):
            if runtime.database is None:
                continue
            try:
                runtime.reads += 1
                rows = await self.shard_collection(runtime.shard_id).find(query).sort([("created_at", DESCENDING), ("media_id", DESCENDING)]).limit(per_shard).to_list(length=per_shard)
                results.extend(rows)
            except Exception:
                runtime.errors += 1
                self._metrics["errors"] += 1
        results.sort(key=lambda x: (x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), x.get("media_id", "")), reverse=True)
        return results[:limit]

    async def search_media_text(self, text_query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        q = str(text_query).strip()
        if not q:
            return []
        regex = {"$regex": re.escape(q), "$options": "i"}
        return await self.search_media({"$or": [{"filename": regex}, {"title": regex}, {"name": regex}, {"quality": regex}, {"language": regex}]}, limit=limit)

    async def count_media(self, query: Optional[dict[str, Any]] = None) -> int:
        query = query or {}
        total = 0
        for runtime in self._shards.values():
            if runtime.database is None:
                continue
            try:
                total += await self.shard_collection(runtime.shard_id).count_documents(query)
            except Exception:
                runtime.errors += 1
        return total

    # ------------------------------------------------------------------
    # Legacy user API — intentionally methods of DatabaseManager.
    # ------------------------------------------------------------------

    async def is_user_exist(self, user_id: int) -> bool:
        return await self.users.find_one({"$or": [{"_id": int(user_id)}, {"id": int(user_id)}, {"user_id": int(user_id)}]}, {"_id": 1}) is not None

    async def get_user(self, user_id: int):
        return await self.users.find_one({"$or": [{"_id": int(user_id)}, {"id": int(user_id)}, {"user_id": int(user_id)}]})

    async def add_user(self, user_id: int, name: Optional[str] = None, **data):
        user_id = int(user_id)
        if name is not None:
            data.setdefault("name", name)
        data.setdefault("user_id", user_id)
        data.setdefault("id", user_id)
        data.setdefault("created_at", utcnow())
        data["updated_at"] = utcnow()
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": data, "$setOnInsert": {"user_id": user_id, "id": user_id, "created_at": data["created_at"]}},
            upsert=True,
        )
        return await self.get_user(user_id)

    async def update_user(self, user_id: int, **data):
        data["updated_at"] = utcnow()
        await self.users.update_one({"user_id": int(user_id)}, {"$set": data}, upsert=True)
        return await self.get_user(user_id)

    async def delete_user(self, user_id: int) -> bool:
        result = await self.users.delete_many({"user_id": int(user_id)})
        return result.deleted_count > 0

    async def get_ban_status(self, user_id: int):
        user = await self.get_user(user_id)
        if not user:
            return {"is_banned": False, "ban_reason": ""}
        nested = user.get("ban_status")
        if isinstance(nested, dict):
            return nested
        return {"is_banned": bool(user.get("is_banned", user.get("banned", False))), "ban_reason": user.get("ban_reason", "")}

    async def ban_user(self, user_id: int, ban_reason: str = "No Reason"):
        return await self.update_user(int(user_id), is_banned=True, banned=True, ban_reason=ban_reason, ban_status={"is_banned": True, "ban_reason": ban_reason})

    async def unban_user(self, user_id: int):
        return await self.update_user(int(user_id), is_banned=False, banned=False, ban_reason="", ban_status={"is_banned": False, "ban_reason": ""})

    async def remove_ban(self, user_id: int):
        return await self.unban_user(user_id)

    async def total_users_count(self) -> int:
        return await self.users.count_documents({})

    async def get_all_users(self):
        return self.users.find({})

    async def get_banned(self):
        users = self.users.find({"$or": [{"is_banned": True}, {"banned": True}, {"ban_status.is_banned": True}]}, {"user_id": 1, "id": 1})
        groups = self.groups.find({"$or": [{"is_disabled": True}, {"chat_status.is_disabled": True}]}, {"chat_id": 1, "id": 1})
        user_ids = []
        chat_ids = []
        async for row in users:
            user_ids.append(row.get("user_id", row.get("id")))
        async for row in groups:
            chat_ids.append(row.get("chat_id", row.get("id")))
        return user_ids, chat_ids

    async def set_premium(self, user_id: int, enabled: bool = True, until: Optional[datetime] = None, **kwargs):
        return await self.update_user(user_id, is_premium=bool(enabled), premium_until=until, premium=bool(enabled), **kwargs)

    async def get_premium_status(self, user_id: int):
        user = await self.get_user(user_id)
        if not user:
            return False
        until = user.get("premium_until")
        if until and isinstance(until, datetime) and utcnow() >= until:
            await self.set_premium(user_id, False)
            return False
        return bool(user.get("is_premium", user.get("premium", False)))

    async def is_premium(self, user_id: int) -> bool:
        return bool(await self.get_premium_status(user_id))

    async def set_verified(self, user_id: int, enabled: bool = True, until: Optional[datetime] = None):
        return await self.update_user(user_id, is_verified=bool(enabled), verified=bool(enabled), verification_until=until)

    async def is_verified(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False
        until = user.get("verification_until")
        if until and isinstance(until, datetime) and utcnow() >= until:
            await self.set_verified(user_id, False)
            return False
        return bool(user.get("is_verified", user.get("verified", False)))

    # ------------------------------------------------------------------
    # Legacy group API.
    # ------------------------------------------------------------------

    async def add_chat(self, chat, title: str):
        chat_id = int(chat)
        await self.groups.update_one(
            {"chat_id": chat_id},
            {"$set": {"chat_id": chat_id, "id": chat_id, "title": title, "updated_at": utcnow()},
             "$setOnInsert": {"created_at": utcnow(), "chat_status": {"is_disabled": False, "reason": ""}}},
            upsert=True,
        )
        return await self.groups.find_one({"chat_id": chat_id})

    async def get_chat(self, chat):
        row = await self.groups.find_one({"chat_id": int(chat)})
        return False if not row else row.get("chat_status", {"is_disabled": False, "reason": ""})

    async def delete_chat(self, chat_id: int) -> bool:
        result = await self.groups.delete_many({"chat_id": int(chat_id)})
        return result.deleted_count > 0

    async def ban_chat(self, chat_id: int, reason: str = "No Reason"):
        return await self.groups.update_one({"chat_id": int(chat_id)}, {"$set": {"chat_status": {"is_disabled": True, "reason": reason}, "is_disabled": True}}, upsert=True)

    async def re_enable_chat(self, chat_id: int):
        return await self.groups.update_one({"chat_id": int(chat_id)}, {"$set": {"chat_status": {"is_disabled": False, "reason": ""}, "is_disabled": False}}, upsert=True)

    async def update_settings(self, entity_id: int, settings: dict[str, Any]):
        return await self.groups.update_one({"chat_id": int(entity_id)}, {"$set": {"settings": settings, "updated_at": utcnow()}}, upsert=True)

    async def get_settings(self, entity_id: int) -> dict[str, Any]:
        row = await self.groups.find_one({"chat_id": int(entity_id)}, {"settings": 1})
        return row.get("settings", {}) if row else {}

    # ------------------------------------------------------------------
    # Generic core CRUD.
    # ------------------------------------------------------------------

    async def insert_one(self, collection: str, document: dict[str, Any], *, session=None):
        document = dict(document)
        result = await self.collection(collection).insert_one(document, session=session)
        self._metrics["writes"] += 1
        return result

    async def find_one(self, collection: str, query: dict[str, Any], projection=None, *, session=None):
        self._metrics["reads"] += 1
        return await self.collection(collection).find_one(query, projection, session=session)

    async def find_many(self, collection: str, query=None, *, limit=100, sort=None, session=None):
        query = query or {}
        cursor = self.collection(collection).find(query, session=session)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.limit(max(1, min(int(limit), 1000))).to_list(length=max(1, min(int(limit), 1000)))

    async def update_one(self, collection: str, query: dict[str, Any], update: dict[str, Any], *, upsert=False, session=None):
        result = await self.collection(collection).update_one(query, update, upsert=upsert, session=session)
        self._metrics["writes"] += 1
        return result

    async def delete_one(self, collection: str, query: dict[str, Any], *, session=None):
        result = await self.collection(collection).delete_one(query, session=session)
        self._metrics["writes"] += 1
        return result

    async def delete_many(self, collection: str, query: dict[str, Any], *, session=None):
        result = await self.collection(collection).delete_many(query, session=session)
        self._metrics["writes"] += 1
        return result

    async def count(self, collection: str, query=None):
        return await self.collection(collection).count_documents(query or {})

    # ------------------------------------------------------------------
    # Catalog API.
    # ------------------------------------------------------------------

    async def create_movie(self, movie_id: str, **fields):
        payload = {"movie_id": str(movie_id), **fields, "updated_at": utcnow()}
        await self.collection(MOVIE_CATALOG).update_one({"movie_id": str(movie_id)}, {"$set": payload, "$setOnInsert": {"created_at": utcnow()}}, upsert=True)
        return await self.collection(MOVIE_CATALOG).find_one({"movie_id": str(movie_id)})

    async def get_movie(self, movie_id: str):
        return await self.collection(MOVIE_CATALOG).find_one({"movie_id": str(movie_id)})

    async def update_movie(self, movie_id: str, **fields):
        await self.collection(MOVIE_CATALOG).update_one({"movie_id": str(movie_id)}, {"$set": {**fields, "updated_at": utcnow()}}, upsert=True)
        return await self.get_movie(movie_id)

    async def delete_movie(self, movie_id: str) -> bool:
        result = await self.collection(MOVIE_CATALOG).delete_one({"movie_id": str(movie_id)})
        return result.deleted_count > 0

    async def create_series(self, series_id: str, **fields):
        payload = {"series_id": str(series_id), **fields, "updated_at": utcnow()}
        await self.collection(SERIES_CATALOG).update_one({"series_id": str(series_id)}, {"$set": payload, "$setOnInsert": {"created_at": utcnow()}}, upsert=True)
        return await self.get_series(series_id)

    async def get_series(self, series_id: str):
        return await self.collection(SERIES_CATALOG).find_one({"series_id": str(series_id)})

    async def update_series(self, series_id: str, **fields):
        await self.collection(SERIES_CATALOG).update_one({"series_id": str(series_id)}, {"$set": {**fields, "updated_at": utcnow()}}, upsert=True)
        return await self.get_series(series_id)

    async def create_episode(self, episode_id: str, series_id: str, **fields):
        payload = {"episode_id": str(episode_id), "series_id": str(series_id), **fields, "updated_at": utcnow()}
        await self.collection(EPISODES).update_one({"episode_id": str(episode_id)}, {"$set": payload, "$setOnInsert": {"created_at": utcnow()}}, upsert=True)
        return await self.collection(EPISODES).find_one({"episode_id": str(episode_id)})

    async def get_episode(self, episode_id: str):
        return await self.collection(EPISODES).find_one({"episode_id": str(episode_id)})

    # ------------------------------------------------------------------
    # Monitoring.
    # ------------------------------------------------------------------

    async def _persist_shard_registry(self):
        for runtime in self._shards.values():
            await self.collection(SHARD_REGISTRY).update_one(
                {"shard_id": runtime.shard_id},
                {"$set": {
                    "shard_id": runtime.shard_id,
                    "number": runtime.config.number,
                    "database": runtime.config.database,
                    "enabled": runtime.config.enabled,
                    "limit_mb": runtime.config.limit_mb,
                    "threshold_percent": runtime.config.threshold_percent,
                    "updated_at": utcnow(),
                }, "$setOnInsert": {"created_at": utcnow()}},
                upsert=True,
            )

    async def _persist_monitoring(self, runtime: ShardRuntime):
        await self.collection(SHARD_MONITORING).update_one(
            {"shard_id": runtime.shard_id},
            {"$set": self._shard_status(runtime)},
            upsert=True,
        )

    def _shard_status(self, runtime: ShardRuntime) -> dict[str, Any]:
        return {
            "shard_id": runtime.shard_id,
            "number": runtime.config.number,
            "healthy": runtime.healthy,
            "accepting_writes": runtime.accepting_writes,
            "recovering": runtime.recovering,
            "active_write_shard": runtime.shard_id == self._active_write_shard,
            "logical_database_size": runtime.logical_size_bytes,
            "document_count": runtime.document_count,
            "limit_bytes": runtime.config.limit_bytes,
            "threshold_bytes": runtime.threshold_bytes,
            "utilization_percent": runtime.utilization_percent,
            "reads": runtime.reads,
            "writes": runtime.writes,
            "errors": runtime.errors,
            "last_latency_ms": runtime.last_latency_ms,
            "last_success": runtime.last_success,
            "last_failure": runtime.last_failure,
            "last_capacity_check": runtime.last_capacity_check,
            "failure_reason": runtime.failure_reason,
            "recovery_attempts": runtime.recovery_attempts,
        }

    async def refresh_all_monitoring(self):
        for runtime in self._shards.values():
            if runtime.database is None and runtime.config.enabled:
                await self._connect_shard(runtime)
            if runtime.database is not None:
                await self.refresh_shard_capacity(runtime)
            await self._persist_monitoring(runtime)
        await self._persist_shard_registry()

    async def monitor_once(self):
        await self.refresh_all_monitoring()
        await self.refresh_active_write_shard()

    async def _monitor_loop(self):
        while self.initialized or self._monitor_task is not None:
            try:
                await self.monitor_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("MongoDB monitor loop failed.")
            await asyncio.sleep(max(5, self.config.monitor_interval_seconds))

    def _start_monitor_task(self):
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop(), name="downtown-villa-mongodb-monitor")

    def shard_status(self) -> list[dict[str, Any]]:
        return [self._shard_status(s) for s in sorted(self._shards.values(), key=lambda x: x.config.number)]

    async def status(self) -> dict[str, Any]:
        healthy = await self.health_check()
        return {
            "provider": "mongodb",
            "initialized": self.initialized,
            "healthy": healthy,
            "core": {
                "database": self.config.database,
                "uri": self.config.sanitized_uri(),
            },
            "media": {
                "shard_count": len(self._shards),
                "active_write_shard": self._active_write_shard,
                "shards": self.shard_status(),
            },
            "metrics": dict(self._metrics),
        }

    # ------------------------------------------------------------------
    # Session / transaction API.
    # ------------------------------------------------------------------

    async def start_session(self):
        return await self.create_client().start_session()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        session = await self.start_session()
        try:
            async with session.start_transaction():
                yield session
        finally:
            await session.end_session()

    async def command(self, command: Any):
        self._metrics["reads"] += 1
        return await self.get_database().command(command)

    # ------------------------------------------------------------------
    # Shutdown.
    # ------------------------------------------------------------------

    async def close(self):
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        for runtime in self._shards.values():
            if runtime.client is not None:
                try:
                    runtime.client.close()
                except Exception:
                    logger.exception("Unable to close shard %s", runtime.shard_id)
            runtime.client = None
            runtime.database = None
            runtime.healthy = False
            runtime.accepting_writes = False
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                logger.exception("Unable to close core MongoDB client")
        self.client = None
        self.database = None
        self.initialized = False
        self._active_write_shard = None

    async def disconnect(self):
        await self.close()

    async def shutdown(self):
        await self.close()


_database_manager: Optional[DatabaseManager] = None


def get_database_manager(app: Any = None) -> Optional[DatabaseManager]:
    global _database_manager
    if app is not None:
        for attr in ("db", "database"):
            existing = getattr(app, attr, None)
            if isinstance(existing, DatabaseManager):
                _database_manager = existing
                return existing
    return _database_manager


def set_database_manager(manager: DatabaseManager, app: Any = None) -> DatabaseManager:
    global _database_manager
    _database_manager = manager
    if app is not None:
        try:
            app.db = manager
        except Exception:
            logger.debug("Unable to attach database manager to app.", exc_info=True)
    return manager


async def initialize(app: Any = None, config: Any = None) -> DatabaseManager:
    existing = get_database_manager(app)
    if existing is not None:
        if not existing.initialized:
            await existing.initialize()
        return existing
    if config is None and app is not None:
        config = getattr(app, "config", None)
    manager = DatabaseManager(DatabaseConfig.from_config(config))
    await manager.initialize()
    set_database_manager(manager, app)
    return manager


async def init_database(app: Any = None, config: Any = None) -> DatabaseManager:
    return await initialize(app=app, config=config)


def get_database(app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return manager.get_database()


def get_collection(name: str, app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return manager.collection(name)


async def health_check(app: Any = None) -> bool:
    manager = get_database_manager(app)
    return await manager.health_check() if manager else False


async def ping(app: Any = None) -> bool:
    return await health_check(app)


async def get_write_shard(app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return await manager.get_write_shard()


async def insert_media(document: dict[str, Any], app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return await manager.insert_media(document)


async def get_media(media_id: str, app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return await manager.get_media(media_id)


async def get_media_location(media_id: str, app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        raise RuntimeError("Database has not been initialized.")
    return await manager.get_media_location(media_id)


async def close(app: Any = None):
    global _database_manager
    manager = get_database_manager(app)
    if manager is None:
        return
    await manager.close()
    if manager is _database_manager:
        _database_manager = None
    if app is not None:
        try:
            app.db = None
        except Exception:
            pass


async def disconnect(app: Any = None):
    await close(app)


async def status(app: Any = None):
    manager = get_database_manager(app)
    if manager is None:
        return {"provider": "mongodb", "initialized": False, "healthy": False}
    return await manager.status()


async def reset_manager():
    await close()


def is_mongodb_available() -> bool:
    return True


def is_sqlalchemy_available() -> bool:
    return False


def get_engine(app: Any = None):
    return None


def get_session_factory(app: Any = None):
    return None


__all__ = [
    "DatabaseConfig",
    "MediaShardConfig",
    "ShardRuntime",
    "DatabaseManager",
    "CORE_SHARD_ID",
    "MEDIA_FILES",
    "MEDIA_LOCATIONS",
    "MOVIE_CATALOG",
    "SERIES_CATALOG",
    "EPISODES",
    "get_database_manager",
    "set_database_manager",
    "initialize",
    "init_database",
    "get_database",
    "get_collection",
    "health_check",
    "ping",
    "get_write_shard",
    "insert_media",
    "get_media",
    "get_media_location",
    "close",
    "disconnect",
    "status",
    "reset_manager",
    "is_mongodb_available",
    "is_sqlalchemy_available",
    "get_engine",
    "get_session_factory",
]


class DatabaseCompatibilityAPI:
    """Extended compatibility surface for future DOWNTOWN VILLA services."""
    async def get_user(self, *args, **kwargs):
        """Compatibility API: get_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_user', *args, **kwargs)
        return None

    async def create_user(self, *args, **kwargs):
        """Compatibility API: create_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_user', *args, **kwargs)
        return None

    async def update_user(self, *args, **kwargs):
        """Compatibility API: update_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_user', *args, **kwargs)
        return None

    async def delete_user(self, *args, **kwargs):
        """Compatibility API: delete_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_user', *args, **kwargs)
        return None

    async def count_user(self, *args, **kwargs):
        """Compatibility API: count_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_user', *args, **kwargs)
        return None

    async def exists_user(self, *args, **kwargs):
        """Compatibility API: exists_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_user', *args, **kwargs)
        return None

    async def list_user(self, *args, **kwargs):
        """Compatibility API: list_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_user', *args, **kwargs)
        return None

    async def search_user(self, *args, **kwargs):
        """Compatibility API: search_user. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_user', *args, **kwargs)
        return None

    async def get_group(self, *args, **kwargs):
        """Compatibility API: get_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_group', *args, **kwargs)
        return None

    async def create_group(self, *args, **kwargs):
        """Compatibility API: create_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_group', *args, **kwargs)
        return None

    async def update_group(self, *args, **kwargs):
        """Compatibility API: update_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_group', *args, **kwargs)
        return None

    async def delete_group(self, *args, **kwargs):
        """Compatibility API: delete_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_group', *args, **kwargs)
        return None

    async def count_group(self, *args, **kwargs):
        """Compatibility API: count_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_group', *args, **kwargs)
        return None

    async def exists_group(self, *args, **kwargs):
        """Compatibility API: exists_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_group', *args, **kwargs)
        return None

    async def list_group(self, *args, **kwargs):
        """Compatibility API: list_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_group', *args, **kwargs)
        return None

    async def search_group(self, *args, **kwargs):
        """Compatibility API: search_group. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_group', *args, **kwargs)
        return None

    async def get_premium(self, *args, **kwargs):
        """Compatibility API: get_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_premium', *args, **kwargs)
        return None

    async def create_premium(self, *args, **kwargs):
        """Compatibility API: create_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_premium', *args, **kwargs)
        return None

    async def update_premium(self, *args, **kwargs):
        """Compatibility API: update_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_premium', *args, **kwargs)
        return None

    async def delete_premium(self, *args, **kwargs):
        """Compatibility API: delete_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_premium', *args, **kwargs)
        return None

    async def count_premium(self, *args, **kwargs):
        """Compatibility API: count_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_premium', *args, **kwargs)
        return None

    async def exists_premium(self, *args, **kwargs):
        """Compatibility API: exists_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_premium', *args, **kwargs)
        return None

    async def list_premium(self, *args, **kwargs):
        """Compatibility API: list_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_premium', *args, **kwargs)
        return None

    async def search_premium(self, *args, **kwargs):
        """Compatibility API: search_premium. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_premium', *args, **kwargs)
        return None

    async def get_verification(self, *args, **kwargs):
        """Compatibility API: get_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_verification', *args, **kwargs)
        return None

    async def create_verification(self, *args, **kwargs):
        """Compatibility API: create_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_verification', *args, **kwargs)
        return None

    async def update_verification(self, *args, **kwargs):
        """Compatibility API: update_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_verification', *args, **kwargs)
        return None

    async def delete_verification(self, *args, **kwargs):
        """Compatibility API: delete_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_verification', *args, **kwargs)
        return None

    async def count_verification(self, *args, **kwargs):
        """Compatibility API: count_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_verification', *args, **kwargs)
        return None

    async def exists_verification(self, *args, **kwargs):
        """Compatibility API: exists_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_verification', *args, **kwargs)
        return None

    async def list_verification(self, *args, **kwargs):
        """Compatibility API: list_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_verification', *args, **kwargs)
        return None

    async def search_verification(self, *args, **kwargs):
        """Compatibility API: search_verification. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_verification', *args, **kwargs)
        return None

    async def get_referral(self, *args, **kwargs):
        """Compatibility API: get_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_referral', *args, **kwargs)
        return None

    async def create_referral(self, *args, **kwargs):
        """Compatibility API: create_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_referral', *args, **kwargs)
        return None

    async def update_referral(self, *args, **kwargs):
        """Compatibility API: update_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_referral', *args, **kwargs)
        return None

    async def delete_referral(self, *args, **kwargs):
        """Compatibility API: delete_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_referral', *args, **kwargs)
        return None

    async def count_referral(self, *args, **kwargs):
        """Compatibility API: count_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_referral', *args, **kwargs)
        return None

    async def exists_referral(self, *args, **kwargs):
        """Compatibility API: exists_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_referral', *args, **kwargs)
        return None

    async def list_referral(self, *args, **kwargs):
        """Compatibility API: list_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_referral', *args, **kwargs)
        return None

    async def search_referral(self, *args, **kwargs):
        """Compatibility API: search_referral. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_referral', *args, **kwargs)
        return None

    async def get_setting(self, *args, **kwargs):
        """Compatibility API: get_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_setting', *args, **kwargs)
        return None

    async def create_setting(self, *args, **kwargs):
        """Compatibility API: create_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_setting', *args, **kwargs)
        return None

    async def update_setting(self, *args, **kwargs):
        """Compatibility API: update_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_setting', *args, **kwargs)
        return None

    async def delete_setting(self, *args, **kwargs):
        """Compatibility API: delete_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_setting', *args, **kwargs)
        return None

    async def count_setting(self, *args, **kwargs):
        """Compatibility API: count_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_setting', *args, **kwargs)
        return None

    async def exists_setting(self, *args, **kwargs):
        """Compatibility API: exists_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_setting', *args, **kwargs)
        return None

    async def list_setting(self, *args, **kwargs):
        """Compatibility API: list_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_setting', *args, **kwargs)
        return None

    async def search_setting(self, *args, **kwargs):
        """Compatibility API: search_setting. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_setting', *args, **kwargs)
        return None

    async def get_movie(self, *args, **kwargs):
        """Compatibility API: get_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_movie', *args, **kwargs)
        return None

    async def create_movie(self, *args, **kwargs):
        """Compatibility API: create_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_movie', *args, **kwargs)
        return None

    async def update_movie(self, *args, **kwargs):
        """Compatibility API: update_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_movie', *args, **kwargs)
        return None

    async def delete_movie(self, *args, **kwargs):
        """Compatibility API: delete_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_movie', *args, **kwargs)
        return None

    async def count_movie(self, *args, **kwargs):
        """Compatibility API: count_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_movie', *args, **kwargs)
        return None

    async def exists_movie(self, *args, **kwargs):
        """Compatibility API: exists_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_movie', *args, **kwargs)
        return None

    async def list_movie(self, *args, **kwargs):
        """Compatibility API: list_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_movie', *args, **kwargs)
        return None

    async def search_movie(self, *args, **kwargs):
        """Compatibility API: search_movie. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_movie', *args, **kwargs)
        return None

    async def get_series(self, *args, **kwargs):
        """Compatibility API: get_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_series', *args, **kwargs)
        return None

    async def create_series(self, *args, **kwargs):
        """Compatibility API: create_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_series', *args, **kwargs)
        return None

    async def update_series(self, *args, **kwargs):
        """Compatibility API: update_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_series', *args, **kwargs)
        return None

    async def delete_series(self, *args, **kwargs):
        """Compatibility API: delete_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_series', *args, **kwargs)
        return None

    async def count_series(self, *args, **kwargs):
        """Compatibility API: count_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_series', *args, **kwargs)
        return None

    async def exists_series(self, *args, **kwargs):
        """Compatibility API: exists_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_series', *args, **kwargs)
        return None

    async def list_series(self, *args, **kwargs):
        """Compatibility API: list_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_series', *args, **kwargs)
        return None

    async def search_series(self, *args, **kwargs):
        """Compatibility API: search_series. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_series', *args, **kwargs)
        return None

    async def get_episode(self, *args, **kwargs):
        """Compatibility API: get_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_episode', *args, **kwargs)
        return None

    async def create_episode(self, *args, **kwargs):
        """Compatibility API: create_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_episode', *args, **kwargs)
        return None

    async def update_episode(self, *args, **kwargs):
        """Compatibility API: update_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_episode', *args, **kwargs)
        return None

    async def delete_episode(self, *args, **kwargs):
        """Compatibility API: delete_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_episode', *args, **kwargs)
        return None

    async def count_episode(self, *args, **kwargs):
        """Compatibility API: count_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_episode', *args, **kwargs)
        return None

    async def exists_episode(self, *args, **kwargs):
        """Compatibility API: exists_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_episode', *args, **kwargs)
        return None

    async def list_episode(self, *args, **kwargs):
        """Compatibility API: list_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_episode', *args, **kwargs)
        return None

    async def search_episode(self, *args, **kwargs):
        """Compatibility API: search_episode. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_episode', *args, **kwargs)
        return None

    async def get_media(self, *args, **kwargs):
        """Compatibility API: get_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_media', *args, **kwargs)
        return None

    async def create_media(self, *args, **kwargs):
        """Compatibility API: create_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_media', *args, **kwargs)
        return None

    async def update_media(self, *args, **kwargs):
        """Compatibility API: update_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_media', *args, **kwargs)
        return None

    async def delete_media(self, *args, **kwargs):
        """Compatibility API: delete_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_media', *args, **kwargs)
        return None

    async def count_media(self, *args, **kwargs):
        """Compatibility API: count_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_media', *args, **kwargs)
        return None

    async def exists_media(self, *args, **kwargs):
        """Compatibility API: exists_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_media', *args, **kwargs)
        return None

    async def list_media(self, *args, **kwargs):
        """Compatibility API: list_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_media', *args, **kwargs)
        return None

    async def search_media(self, *args, **kwargs):
        """Compatibility API: search_media. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_media', *args, **kwargs)
        return None

    async def get_request(self, *args, **kwargs):
        """Compatibility API: get_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_request', *args, **kwargs)
        return None

    async def create_request(self, *args, **kwargs):
        """Compatibility API: create_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_request', *args, **kwargs)
        return None

    async def update_request(self, *args, **kwargs):
        """Compatibility API: update_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_request', *args, **kwargs)
        return None

    async def delete_request(self, *args, **kwargs):
        """Compatibility API: delete_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_request', *args, **kwargs)
        return None

    async def count_request(self, *args, **kwargs):
        """Compatibility API: count_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_request', *args, **kwargs)
        return None

    async def exists_request(self, *args, **kwargs):
        """Compatibility API: exists_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_request', *args, **kwargs)
        return None

    async def list_request(self, *args, **kwargs):
        """Compatibility API: list_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_request', *args, **kwargs)
        return None

    async def search_request(self, *args, **kwargs):
        """Compatibility API: search_request. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_request', *args, **kwargs)
        return None

    async def get_analytics(self, *args, **kwargs):
        """Compatibility API: get_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_analytics', *args, **kwargs)
        return None

    async def create_analytics(self, *args, **kwargs):
        """Compatibility API: create_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_analytics', *args, **kwargs)
        return None

    async def update_analytics(self, *args, **kwargs):
        """Compatibility API: update_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_analytics', *args, **kwargs)
        return None

    async def delete_analytics(self, *args, **kwargs):
        """Compatibility API: delete_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_analytics', *args, **kwargs)
        return None

    async def count_analytics(self, *args, **kwargs):
        """Compatibility API: count_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_analytics', *args, **kwargs)
        return None

    async def exists_analytics(self, *args, **kwargs):
        """Compatibility API: exists_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_analytics', *args, **kwargs)
        return None

    async def list_analytics(self, *args, **kwargs):
        """Compatibility API: list_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_analytics', *args, **kwargs)
        return None

    async def search_analytics(self, *args, **kwargs):
        """Compatibility API: search_analytics. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_analytics', *args, **kwargs)
        return None

    async def get_monitoring(self, *args, **kwargs):
        """Compatibility API: get_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_monitoring', *args, **kwargs)
        return None

    async def create_monitoring(self, *args, **kwargs):
        """Compatibility API: create_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_monitoring', *args, **kwargs)
        return None

    async def update_monitoring(self, *args, **kwargs):
        """Compatibility API: update_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_monitoring', *args, **kwargs)
        return None

    async def delete_monitoring(self, *args, **kwargs):
        """Compatibility API: delete_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_monitoring', *args, **kwargs)
        return None

    async def count_monitoring(self, *args, **kwargs):
        """Compatibility API: count_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_monitoring', *args, **kwargs)
        return None

    async def exists_monitoring(self, *args, **kwargs):
        """Compatibility API: exists_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_monitoring', *args, **kwargs)
        return None

    async def list_monitoring(self, *args, **kwargs):
        """Compatibility API: list_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_monitoring', *args, **kwargs)
        return None

    async def search_monitoring(self, *args, **kwargs):
        """Compatibility API: search_monitoring. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_monitoring', *args, **kwargs)
        return None

    async def get_shard(self, *args, **kwargs):
        """Compatibility API: get_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_shard', *args, **kwargs)
        return None

    async def create_shard(self, *args, **kwargs):
        """Compatibility API: create_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_shard', *args, **kwargs)
        return None

    async def update_shard(self, *args, **kwargs):
        """Compatibility API: update_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_shard', *args, **kwargs)
        return None

    async def delete_shard(self, *args, **kwargs):
        """Compatibility API: delete_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_shard', *args, **kwargs)
        return None

    async def count_shard(self, *args, **kwargs):
        """Compatibility API: count_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_shard', *args, **kwargs)
        return None

    async def exists_shard(self, *args, **kwargs):
        """Compatibility API: exists_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_shard', *args, **kwargs)
        return None

    async def list_shard(self, *args, **kwargs):
        """Compatibility API: list_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_shard', *args, **kwargs)
        return None

    async def search_shard(self, *args, **kwargs):
        """Compatibility API: search_shard. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_shard', *args, **kwargs)
        return None

    async def get_catalog(self, *args, **kwargs):
        """Compatibility API: get_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_catalog', *args, **kwargs)
        return None

    async def create_catalog(self, *args, **kwargs):
        """Compatibility API: create_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_catalog', *args, **kwargs)
        return None

    async def update_catalog(self, *args, **kwargs):
        """Compatibility API: update_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_catalog', *args, **kwargs)
        return None

    async def delete_catalog(self, *args, **kwargs):
        """Compatibility API: delete_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_catalog', *args, **kwargs)
        return None

    async def count_catalog(self, *args, **kwargs):
        """Compatibility API: count_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_catalog', *args, **kwargs)
        return None

    async def exists_catalog(self, *args, **kwargs):
        """Compatibility API: exists_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_catalog', *args, **kwargs)
        return None

    async def list_catalog(self, *args, **kwargs):
        """Compatibility API: list_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_catalog', *args, **kwargs)
        return None

    async def search_catalog(self, *args, **kwargs):
        """Compatibility API: search_catalog. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_catalog', *args, **kwargs)
        return None

    async def get_bot_state(self, *args, **kwargs):
        """Compatibility API: get_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_bot_state', *args, **kwargs)
        return None

    async def create_bot_state(self, *args, **kwargs):
        """Compatibility API: create_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_bot_state', *args, **kwargs)
        return None

    async def update_bot_state(self, *args, **kwargs):
        """Compatibility API: update_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_bot_state', *args, **kwargs)
        return None

    async def delete_bot_state(self, *args, **kwargs):
        """Compatibility API: delete_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_bot_state', *args, **kwargs)
        return None

    async def count_bot_state(self, *args, **kwargs):
        """Compatibility API: count_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_bot_state', *args, **kwargs)
        return None

    async def exists_bot_state(self, *args, **kwargs):
        """Compatibility API: exists_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_bot_state', *args, **kwargs)
        return None

    async def list_bot_state(self, *args, **kwargs):
        """Compatibility API: list_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_bot_state', *args, **kwargs)
        return None

    async def search_bot_state(self, *args, **kwargs):
        """Compatibility API: search_bot_state. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_bot_state', *args, **kwargs)
        return None

    async def get_log(self, *args, **kwargs):
        """Compatibility API: get_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_log', *args, **kwargs)
        return None

    async def create_log(self, *args, **kwargs):
        """Compatibility API: create_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_log', *args, **kwargs)
        return None

    async def update_log(self, *args, **kwargs):
        """Compatibility API: update_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_log', *args, **kwargs)
        return None

    async def delete_log(self, *args, **kwargs):
        """Compatibility API: delete_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_log', *args, **kwargs)
        return None

    async def count_log(self, *args, **kwargs):
        """Compatibility API: count_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_log', *args, **kwargs)
        return None

    async def exists_log(self, *args, **kwargs):
        """Compatibility API: exists_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_log', *args, **kwargs)
        return None

    async def list_log(self, *args, **kwargs):
        """Compatibility API: list_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_log', *args, **kwargs)
        return None

    async def search_log(self, *args, **kwargs):
        """Compatibility API: search_log. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_log', *args, **kwargs)
        return None

    async def get_search(self, *args, **kwargs):
        """Compatibility API: get_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('get_search', *args, **kwargs)
        return None

    async def create_search(self, *args, **kwargs):
        """Compatibility API: create_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('create_search', *args, **kwargs)
        return None

    async def update_search(self, *args, **kwargs):
        """Compatibility API: update_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('update_search', *args, **kwargs)
        return None

    async def delete_search(self, *args, **kwargs):
        """Compatibility API: delete_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('delete_search', *args, **kwargs)
        return None

    async def count_search(self, *args, **kwargs):
        """Compatibility API: count_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('count_search', *args, **kwargs)
        return None

    async def exists_search(self, *args, **kwargs):
        """Compatibility API: exists_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('exists_search', *args, **kwargs)
        return None

    async def list_search(self, *args, **kwargs):
        """Compatibility API: list_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('list_search', *args, **kwargs)
        return None

    async def search_search(self, *args, **kwargs):
        """Compatibility API: search_search. Delegates to the core MongoDB layer."""
        manager = self if isinstance(self, DatabaseManager) else getattr(self, 'database', self)
        if hasattr(manager, '_compat_dispatch'):
            return await manager._compat_dispatch('search_search', *args, **kwargs)
        return None

    async def _compat_dispatch(self, method, *args, **kwargs):
        category = method.split('_', 1)[-1]
        collection_map = {
            'user': USERS, 'group': GROUPS, 'premium': PREMIUM,
            'verification': VERIFICATION, 'referral': REFERRALS,
            'setting': SETTINGS, 'movie': MOVIE_CATALOG,
            'series': SERIES_CATALOG, 'episode': EPISODES,
            'media': MEDIA_FILES, 'request': REQUESTS,
            'analytics': ANALYTICS, 'log': LOGS,
            'bot_state': BOT_STATE,
        }
        collection = collection_map.get(category)
        if not collection:
            return None
        action = method.split('_', 1)[0]
        query = kwargs.pop('query', {})
        if args and isinstance(args[0], dict):
            query = args[0]
        if action == 'get':
            return await self.collection(collection).find_one(query)
        if action == 'list':
            limit = max(1, min(int(kwargs.pop('limit', 100)), 1000))
            return await self.collection(collection).find(query).limit(limit).to_list(length=limit)
        if action == 'count':
            return await self.collection(collection).count_documents(query)
        if action == 'exists':
            return await self.collection(collection).find_one(query, {'_id': 1}) is not None
        if action == 'search':
            return await self.collection(collection).find(query).limit(int(kwargs.pop('limit', 50))).to_list(length=int(kwargs.get('limit', 50)))
        if action == 'create':
            document = kwargs.pop('document', query or (args[0] if args else {}))
            return await self.collection(collection).insert_one(document)
        if action == 'update':
            update = kwargs.pop('update', {})
            return await self.collection(collection).update_one(query, update, upsert=bool(kwargs.pop('upsert', False)))
        if action == 'delete':
            return await self.collection(collection).delete_one(query)
        return None


# Bind the extended compatibility API without replacing the DatabaseManager
# implementation above. This keeps one authoritative manager contract.
for _name, _value in DatabaseCompatibilityAPI.__dict__.items():
    if _name.startswith('_') or _name == '_compat_dispatch':
        continue
    if not hasattr(DatabaseManager, _name):
        setattr(DatabaseManager, _name, _value)
DatabaseManager._compat_dispatch = DatabaseCompatibilityAPI._compat_dispatch


# =============================================================================
#  PATCHES – fixes for known errors, without modifying original code
# =============================================================================

# 1. Fix add_user – avoid writing user_id in both $set and $setOnInsert
_original_add_user = DatabaseManager.add_user

async def _patched_add_user(self, user_id: int, name: Optional[str] = None, **data):
    user_id = int(user_id)
    if name is not None:
        data.setdefault("name", name)
    # Do NOT include 'user_id' and 'id' in $set – they are already in $setOnInsert
    set_data = {k: v for k, v in data.items() if k not in ('user_id', 'id')}
    set_data.setdefault("updated_at", utcnow())
    # Prepare $setOnInsert: always set user_id, id, created_at
    on_insert = {
        "user_id": user_id,
        "id": user_id,
        "created_at": data.get("created_at", utcnow()),
    }
    await self.users.update_one(
        {"user_id": user_id},
        {"$set": set_data, "$setOnInsert": on_insert},
        upsert=True,
    )
    return await self.get_user(user_id)

DatabaseManager.add_user = _patched_add_user


# 2. Fix initialize_indexes – skip index creation if index already exists with conflicting options
_original_initialize_indexes = DatabaseManager.initialize_indexes

async def _patched_initialize_indexes(self):
    try:
        await _original_initialize_indexes(self)
    except Exception as e:
        # If it's an IndexOptionsConflict, we can ignore it – index already exists
        # Other errors we re-raise
        if isinstance(e, PyMongoError) and "Index already exists with a different name" in str(e):
            logger.warning("Index conflict detected – skipping creation (index already exists).")
            # Optionally, we could log the error but not raise
            return
        raise

DatabaseManager.initialize_indexes = _patched_initialize_indexes


# 3. Patch _initialize_media_indexes similarly (if needed)
_original_initialize_media_indexes = DatabaseManager._initialize_media_indexes

async def _patched_initialize_media_indexes(self, runtime):
    try:
        await _original_initialize_media_indexes(self, runtime)
    except Exception as e:
        if isinstance(e, PyMongoError) and "Index already exists with a different name" in str(e):
            logger.warning("Media index conflict on shard %s – skipping creation.", runtime.shard_id)
            return
        raise

DatabaseManager._initialize_media_indexes = _patched_initialize_media_indexes


# =============================================================================
#  ULTIMATE ADDITIONS – caching, bulk ops, metrics, CLI, etc.
# =============================================================================

# ---------- Local caching layer ----------
@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class DatabaseCache:
    """Simple TTL‑based in‑memory cache for frequently accessed documents."""
    def __init__(self, default_ttl_seconds: int = 300):
        self._store: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl_seconds
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                del self._store[key]
                return None
            return entry.value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expires_at = time.monotonic() + ttl
        async with self._lock:
            self._store[key] = CacheEntry(value=value, expires_at=expires_at)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


# Extend DatabaseManager with cache support
DatabaseManager._cache = DatabaseCache(default_ttl_seconds=300)
DatabaseManager._cache_enabled = True

# Add caching wrappers for common getters (without altering original signatures)
_original_get_user = DatabaseManager.get_user
_original_get_media = DatabaseManager.get_media
_original_get_movie = DatabaseManager.get_movie
_original_get_series = DatabaseManager.get_series
_original_get_episode = DatabaseManager.get_episode


async def _cached_get_user(self, user_id: int):
    if not self._cache_enabled:
        return await _original_get_user(self, user_id)
    key = f"user:{user_id}"
    cached = await self._cache.get(key)
    if cached is not None:
        return cached
    result = await _original_get_user(self, user_id)
    if result:
        await self._cache.set(key, result)
    return result


async def _cached_get_media(self, media_id: str):
    if not self._cache_enabled:
        return await _original_get_media(self, media_id)
    key = f"media:{media_id}"
    cached = await self._cache.get(key)
    if cached is not None:
        return cached
    result = await _original_get_media(self, media_id)
    if result:
        await self._cache.set(key, result)
    return result


# Patch methods (only if not already patched)
if not hasattr(DatabaseManager, '_cache_patched'):
    DatabaseManager.get_user = _cached_get_user
    DatabaseManager.get_media = _cached_get_media
    # similarly for movie, series, episode – omitted for brevity, but can be added.
    DatabaseManager._cache_patched = True


# ---------- Bulk operations ----------
async def bulk_insert_media(self, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert multiple media records, routing each to the appropriate shard."""
    results = []
    for doc in documents:
        results.append(await self.insert_media(doc))
    return results


DatabaseManager.bulk_insert_media = bulk_insert_media


async def bulk_delete_media(self, media_ids: list[str]) -> int:
    """Delete multiple media records by media_id."""
    count = 0
    for mid in media_ids:
        if await self.delete_media(mid):
            count += 1
    return count


DatabaseManager.bulk_delete_media = bulk_delete_media


# ---------- Extended metrics ----------
async def get_metrics(self) -> dict[str, Any]:
    """Return detailed performance metrics including latency and per‑shard stats."""
    base = dict(self._metrics)
    shard_stats = []
    total_latency = 0.0
    for runtime in self._shards.values():
        shard_stats.append({
            "shard_id": runtime.shard_id,
            "reads": runtime.reads,
            "writes": runtime.writes,
            "errors": runtime.errors,
            "avg_latency_ms": runtime.total_latency_ms / max(1, runtime.reads + runtime.writes),
            "utilization": runtime.utilization_percent,
        })
        total_latency += runtime.total_latency_ms
    base["shards"] = shard_stats
    base["total_latency_ms"] = total_latency
    base["cache_enabled"] = getattr(self, "_cache_enabled", False)
    return base


DatabaseManager.get_metrics = get_metrics


# ---------- Scheduled maintenance ----------
async def compact_media_shard(self, shard_id: str) -> dict[str, Any]:
    """Run a compact/repair operation on a media shard (if supported by MongoDB)."""
    runtime = self.shard(shard_id)
    if runtime.database is None:
        raise RuntimeError(f"Shard {shard_id} not connected")
    result = await runtime.database.command({"compact": MEDIA_FILES})
    logger.info("Compaction on shard %s completed: %s", shard_id, result)
    return result


DatabaseManager.compact_media_shard = compact_media_shard


async def cleanup_orphan_media_locations(self) -> int:
    """Remove media_locations entries whose media no longer exists on any shard."""
    locations = await self.media_locations.find({"status": "active"}).to_list(length=10_000)
    removed = 0
    for loc in locations:
        media_id = loc["media_id"]
        shard_id = loc["shard_id"]
        runtime = self._shards.get(shard_id)
        if runtime is None or runtime.database is None:
            continue
        doc = await self.shard_collection(shard_id).find_one({"media_id": media_id}, {"_id": 1})
        if doc is None:
            await self.media_locations.update_one(
                {"media_id": media_id},
                {"$set": {"status": "orphaned", "updated_at": utcnow()}}
            )
            removed += 1
    return removed


DatabaseManager.cleanup_orphan_media_locations = cleanup_orphan_media_locations


# Extend monitor loop to run maintenance periodically
_original_monitor_once = DatabaseManager.monitor_once


async def _monitor_once_with_maintenance(self):
    await _original_monitor_once(self)
    # Run cleanup once per hour (approx)
    if self.initialized and getattr(self, "_last_cleanup", utcnow()) is not None:
        if (utcnow() - self._last_cleanup).total_seconds() > 3600:
            try:
                removed = await self.cleanup_orphan_media_locations()
                if removed:
                    logger.info("Cleaned up %d orphaned media locations", removed)
            except Exception:
                logger.exception("Orphan cleanup failed")
            self._last_cleanup = utcnow()


DatabaseManager.monitor_once = _monitor_once_with_maintenance
DatabaseManager._last_cleanup = utcnow()


# ---------- Command‑line interface ----------
async def main(argv: Optional[list[str]] = None) -> None:
    """Simple CLI for database admin tasks."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Downtown Villa MongoDB CLI")
    parser.add_argument("--uri", help="MongoDB URI (overrides env)")
    parser.add_argument("--db", help="Database name (overrides env)")
    parser.add_argument("command", choices=["status", "shards", "search", "cleanup"],
                        help="Command to run")
    parser.add_argument("--query", help="Search query (JSON)")
    parser.add_argument("--limit", type=int, default=10, help="Limit results")
    args = parser.parse_args(argv)

    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Override env if provided
    if args.uri:
        os.environ["MONGO_URI"] = args.uri
    if args.db:
        os.environ["MONGO_DATABASE"] = args.db

    manager = await initialize()
    try:
        if args.command == "status":
            s = await manager.status()
            print(json.dumps(s, default=str, indent=2))
        elif args.command == "shards":
            for status in manager.shard_status():
                print(json.dumps(status, default=str, indent=2))
        elif args.command == "search":
            import json as json_mod
            query = json_mod.loads(args.query) if args.query else {}
            results = await manager.search_media(query, limit=args.limit)
            for r in results:
                print(json_mod.dumps(r, default=str))
        elif args.command == "cleanup":
            removed = await manager.cleanup_orphan_media_locations()
            print(f"Removed {removed} orphaned entries.")
    finally:
        await manager.close()


if __name__ == "__main__":
    import asyncio, json
    asyncio.run(main())
