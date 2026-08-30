"""
bot.database.connection

DOWNTOWN VILLA BOT
==================

Production MongoDB infrastructure.

ARCHITECTURE
------------

CORE DATABASE
    MONGO_URI
        |
        +-- users
        +-- groups
        +-- premium
        +-- verification
        +-- referrals
        +-- settings
        +-- bot_state
        +-- media_locations
        +-- shard_registry
        +-- shard_monitoring

MEDIA DATABASE POOL
    MONGO_URI_2
    MONGO_URI_3
    MONGO_URI_4
    ...
        |
        +-- media_files
        +-- searchable media metadata

IMPORTANT
---------

MongoDB stores metadata only.

Telegram stores the actual media bytes.

The application server MUST NOT permanently store movie/series files.

SHARDING RULE
-------------

Core DB (#1) is never used as a media shard.

DB #2 onward are media shards.

New media records are written to the first healthy shard whose
configured safety threshold has not been reached.

Existing records are NEVER automatically moved.

Every media record receives a stable internal media_id.

The CORE database stores:

    media_id
    shard_id
    database_name
    collection_name
    created_at
    status

This allows direct lookup without searching every shard.

ENVIRONMENT
-----------

Required:

    MONGO_URI

Optional:

    MONGO_DATABASE

Media shards:

    MONGO_URI_2
    MONGO_URI_3
    MONGO_URI_4
    ...

Each shard can have:

    MONGO_DATABASE_2
    MONGO_DATABASE_3
    MONGO_DATABASE_4
    ...

Capacity:

    MONGO_SHARD_2_LIMIT_MB
    MONGO_SHARD_3_LIMIT_MB
    MONGO_SHARD_4_LIMIT_MB

Threshold:

    MONGO_SHARD_2_THRESHOLD_PERCENT
    MONGO_SHARD_3_THRESHOLD_PERCENT
    MONGO_SHARD_4_THRESHOLD_PERCENT

Example:

    MONGO_URI=<core database URI>

    MONGO_URI_2=<media database URI>
    MONGO_DATABASE_2=downtown_media_02
    MONGO_SHARD_2_LIMIT_MB=450
    MONGO_SHARD_2_THRESHOLD_PERCENT=85

    MONGO_URI_3=<media database URI>
    MONGO_DATABASE_3=downtown_media_03
    MONGO_SHARD_3_LIMIT_MB=450
    MONGO_SHARD_3_THRESHOLD_PERCENT=85

There is no hard-coded maximum number of media shards.

The router discovers sequential MONGO_URI_N variables.

MONITORING
----------

The manager maintains lightweight runtime monitoring:

    health
    active_write_shard
    logical_database_size
    document_count
    reads
    writes
    errors
    latency
    last_success
    last_failure
    recovery_status

The admin dashboard should consume manager.status() instead of
independently hammering every MongoDB deployment.

"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from pymongo import AsyncMongoClient, ASCENDING, DESCENDING
from pymongo.errors import (
    DuplicateKeyError,
    PyMongoError,
    ServerSelectionTimeoutError,
)

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

CORE_SHARD_ID = "core"

CORE_DATABASE_DEFAULT = "telegram_bot"

MEDIA_COLLECTION = "media_files"

MEDIA_LOCATION_COLLECTION = "media_locations"

SHARD_REGISTRY_COLLECTION = "shard_registry"

SHARD_MONITORING_COLLECTION = "shard_monitoring"

DEFAULT_SHARD_LIMIT_MB = 450

DEFAULT_THRESHOLD_PERCENT = 85

DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 10_000

DEFAULT_CONNECT_TIMEOUT_MS = 10_000

DEFAULT_SOCKET_TIMEOUT_MS = 30_000

DEFAULT_APP_NAME = "downtown-villa-bot"

DEFAULT_MONITOR_INTERVAL_SECONDS = 60

DEFAULT_HEALTH_RETRY_SECONDS = 30

DEFAULT_MAX_SHARD_NUMBER = 10_000

SHARD_URI_PATTERN = re.compile(
    r"^MONGO_URI_(\d+)$"
)

# ============================================================================
# TIME
# ============================================================================


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# ENVIRONMENT HELPERS
# ============================================================================


def _safe_int(
    value: Any,
    default: int,
) -> int:

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(
    value: Any,
    default: float,
) -> float:

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(
    value: Any,
    default: bool = False,
) -> bool:

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


# ============================================================================
# URI REDACTION
# ============================================================================


def sanitize_uri(
    uri: str,
) -> str:

    if not uri:
        return "<not-configured>"

    value = str(uri)

    try:

        if "://" not in value:
            return "<redacted>"

        scheme, remainder = value.split(
            "://",
            1,
        )

        if "@" not in remainder:
            return value

        credentials, host = remainder.split(
            "@",
            1,
        )

        if ":" in credentials:

            username = credentials.split(
                ":",
                1,
            )[0]

            credentials = (
                username
                + ":***"
            )

        else:

            credentials = "***"

        return (
            scheme
            + "://"
            + credentials
            + "@"
            + host
        )

    except Exception:

        return "<redacted>"


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass
class MediaShardConfig:
    """
    Configuration for one media MongoDB shard.
    """

    shard_id: str

    number: int

    uri: str

    database: str

    limit_mb: int = DEFAULT_SHARD_LIMIT_MB

    threshold_percent: float = (
        DEFAULT_THRESHOLD_PERCENT
    )

    server_selection_timeout_ms: int = (
        DEFAULT_SERVER_SELECTION_TIMEOUT_MS
    )

    connect_timeout_ms: int = (
        DEFAULT_CONNECT_TIMEOUT_MS
    )

    socket_timeout_ms: int = (
        DEFAULT_SOCKET_TIMEOUT_MS
    )

    application_name: str = (
        DEFAULT_APP_NAME
    )

    enabled: bool = True

    @property
    def limit_bytes(self) -> int:

        return max(
            1,
            self.limit_mb,
        ) * 1024 * 1024

    @property
    def threshold_bytes(self) -> int:

        return int(
            self.limit_bytes
            * (
                self.threshold_percent
                / 100.0
            )
        )

    def sanitized_uri(self) -> str:

        return sanitize_uri(
            self.uri
        )


@dataclass
class DatabaseConfig:
    """
    Complete MongoDB topology configuration.

    DB #1 is the CORE database.

    DB #2 onward are media shards.
    """

    uri: str = ""

    database: str = (
        CORE_DATABASE_DEFAULT
    )

    server_selection_timeout_ms: int = (
        DEFAULT_SERVER_SELECTION_TIMEOUT_MS
    )

    connect_timeout_ms: int = (
        DEFAULT_CONNECT_TIMEOUT_MS
    )

    socket_timeout_ms: int = (
        DEFAULT_SOCKET_TIMEOUT_MS
    )

    application_name: str = (
        DEFAULT_APP_NAME
    )

    monitor_interval_seconds: int = (
        DEFAULT_MONITOR_INTERVAL_SECONDS
    )

    recovery_retry_seconds: int = (
        DEFAULT_HEALTH_RETRY_SECONDS
    )

    shards: list[
        MediaShardConfig
    ] = field(
        default_factory=list
    )

    @classmethod
    def from_environment(
        cls,
    ) -> "DatabaseConfig":

        uri = (
            os.getenv("MONGO_URI")
            or os.getenv("MONGODB_URI")
            or ""
        ).strip()

        database = (
            os.getenv("MONGO_DATABASE")
            or os.getenv("MONGODB_DATABASE")
            or CORE_DATABASE_DEFAULT
        ).strip()

        application_name = (
            os.getenv("MONGO_APP_NAME")
            or DEFAULT_APP_NAME
        ).strip()

        config = cls(
            uri=uri,
            database=database,
            server_selection_timeout_ms=_safe_int(
                os.getenv(
                    "MONGO_SERVER_SELECTION_TIMEOUT_MS"
                ),
                DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
            ),
            connect_timeout_ms=_safe_int(
                os.getenv(
                    "MONGO_CONNECT_TIMEOUT_MS"
                ),
                DEFAULT_CONNECT_TIMEOUT_MS,
            ),
            socket_timeout_ms=_safe_int(
                os.getenv(
                    "MONGO_SOCKET_TIMEOUT_MS"
                ),
                DEFAULT_SOCKET_TIMEOUT_MS,
            ),
            application_name=application_name,
            monitor_interval_seconds=_safe_int(
                os.getenv(
                    "MONGO_MONITOR_INTERVAL_SECONDS"
                ),
                DEFAULT_MONITOR_INTERVAL_SECONDS,
            ),
            recovery_retry_seconds=_safe_int(
                os.getenv(
                    "MONGO_RECOVERY_RETRY_SECONDS"
                ),
                DEFAULT_HEALTH_RETRY_SECONDS,
            ),
        )

        config.shards = (
            _discover_media_shards(
                config
            )
        )

        return config

    @classmethod
    def from_config(
        cls,
        config: Any,
    ) -> "DatabaseConfig":

        if config is None:
            return cls.from_environment()

        if isinstance(
            config,
            cls,
        ):
            return config

        if isinstance(
            config,
            dict,
        ):

            getter = config.get

        else:

            getter = (
                lambda key, default=None:
                getattr(
                    config,
                    key,
                    default,
                )
            )

        uri = (
            getter("mongo_uri")
            or getter("mongodb_uri")
            or getter("database_uri")
            or getter("uri")
            or os.getenv("MONGO_URI")
            or os.getenv("MONGODB_URI")
            or ""
        )

        database = (
            getter("mongo_database")
            or getter("mongodb_database")
            or getter("database_name")
            or getter("database")
            or os.getenv("MONGO_DATABASE")
            or CORE_DATABASE_DEFAULT
        )

        result = cls(
            uri=str(uri).strip(),
            database=str(database).strip(),
            server_selection_timeout_ms=_safe_int(
                getter(
                    "mongo_server_selection_timeout_ms",
                    os.getenv(
                        "MONGO_SERVER_SELECTION_TIMEOUT_MS"
                    ),
                ),
                DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
            ),
            connect_timeout_ms=_safe_int(
                getter(
                    "mongo_connect_timeout_ms",
                    os.getenv(
                        "MONGO_CONNECT_TIMEOUT_MS"
                    ),
                ),
                DEFAULT_CONNECT_TIMEOUT_MS,
            ),
            socket_timeout_ms=_safe_int(
                getter(
                    "mongo_socket_timeout_ms",
                    os.getenv(
                        "MONGO_SOCKET_TIMEOUT_MS"
                    ),
                ),
                DEFAULT_SOCKET_TIMEOUT_MS,
            ),
            application_name=str(
                getter(
                    "mongo_app_name",
                    os.getenv(
                        "MONGO_APP_NAME",
                        DEFAULT_APP_NAME,
                    ),
                )
            ),
            monitor_interval_seconds=_safe_int(
                getter(
                    "mongo_monitor_interval_seconds",
                    os.getenv(
                        "MONGO_MONITOR_INTERVAL_SECONDS"
                    ),
                ),
                DEFAULT_MONITOR_INTERVAL_SECONDS,
            ),
            recovery_retry_seconds=_safe_int(
                getter(
                    "mongo_recovery_retry_seconds",
                    os.getenv(
                        "MONGO_RECOVERY_RETRY_SECONDS"
                    ),
                ),
                DEFAULT_HEALTH_RETRY_SECONDS,
            ),
        )

        result.shards = (
            _discover_media_shards(
                result
            )
        )

        return result

    def validate(
        self,
    ) -> None:

        if not self.uri:

            raise RuntimeError(
                "MONGO_URI is not configured."
            )

        if not self.database:

            raise RuntimeError(
                "MONGO_DATABASE is not configured."
            )

        seen: set[str] = set()

        for shard in self.shards:

            if shard.shard_id in seen:

                raise RuntimeError(
                    f"Duplicate media shard: "
                    f"{shard.shard_id}"
                )

            seen.add(
                shard.shard_id
            )

            if not shard.uri:

                raise RuntimeError(
                    f"{shard.shard_id} has no URI."
                )

            if (
                shard.threshold_percent
                <= 0
                or shard.threshold_percent
                > 100
            ):

                raise RuntimeError(
                    f"{shard.shard_id} has invalid "
                    f"threshold."
                )

            if shard.limit_mb <= 0:

                raise RuntimeError(
                    f"{shard.shard_id} has invalid "
                    f"capacity."
                )

    def sanitized_uri(
        self,
    ) -> str:

        return sanitize_uri(
            self.uri
        )


# ============================================================================
# SHARD DISCOVERY
# ============================================================================


def _discover_media_shards(
    config: DatabaseConfig,
) -> list[MediaShardConfig]:

    discovered: list[
        MediaShardConfig
    ] = []

    numbers: list[int] = []

    for key, value in os.environ.items():

        match = SHARD_URI_PATTERN.match(
            key
        )

        if not match:
            continue

        number = int(
            match.group(1)
        )

        if number < 2:
            continue

        if number > DEFAULT_MAX_SHARD_NUMBER:
            logger.warning(
                "Ignoring %s: shard number too large.",
                key,
            )
            continue

        if not value.strip():
            continue

        numbers.append(
            number
        )

    for number in sorted(
        set(numbers)
    ):

        uri = os.getenv(
            f"MONGO_URI_{number}",
            "",
        ).strip()

        if not uri:
            continue

        database = (
            os.getenv(
                f"MONGO_DATABASE_{number}"
            )
            or f"downtown_media_{number:02d}"
        ).strip()

        limit_mb = _safe_int(
            os.getenv(
                f"MONGO_SHARD_{number}_LIMIT_MB"
            ),
            DEFAULT_SHARD_LIMIT_MB,
        )

        threshold = _safe_float(
            os.getenv(
                f"MONGO_SHARD_{number}_THRESHOLD_PERCENT"
            ),
            DEFAULT_THRESHOLD_PERCENT,
        )

        enabled = _safe_bool(
            os.getenv(
                f"MONGO_SHARD_{number}_ENABLED"
            ),
            True,
        )

        discovered.append(
            MediaShardConfig(
                shard_id=f"media_{number}",
                number=number,
                uri=uri,
                database=database,
                limit_mb=limit_mb,
                threshold_percent=threshold,
                server_selection_timeout_ms=_safe_int(
                    os.getenv(
                        f"MONGO_SHARD_{number}_SERVER_SELECTION_TIMEOUT_MS"
                    ),
                    config.server_selection_timeout_ms,
                ),
                connect_timeout_ms=_safe_int(
                    os.getenv(
                        f"MONGO_SHARD_{number}_CONNECT_TIMEOUT_MS"
                    ),
                    config.connect_timeout_ms,
                ),
                socket_timeout_ms=_safe_int(
                    os.getenv(
                        f"MONGO_SHARD_{number}_SOCKET_TIMEOUT_MS"
                    ),
                    config.socket_timeout_ms,
                ),
                application_name=(
                    f"{config.application_name}-media-{number}"
                ),
                enabled=enabled,
            )
        )

    return discovered


# ============================================================================
# SHARD RUNTIME STATE
# ============================================================================


@dataclass
class ShardRuntime:
    """
    Runtime state for a MongoDB shard.
    """

    config: MediaShardConfig

    client: Optional[
        AsyncMongoClient
    ] = None

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

    last_success: Optional[
        datetime
    ] = None

    last_failure: Optional[
        datetime
    ] = None

    last_capacity_check: Optional[
        datetime
    ] = None

    failure_reason: Optional[
        str
    ] = None

    recovery_attempts: int = 0

    lock: asyncio.Lock = field(
        default_factory=asyncio.Lock
    )

    @property
    def shard_id(self) -> str:

        return self.config.shard_id

    @property
    def threshold_bytes(self) -> int:

        return self.config.threshold_bytes

    @property
    def utilization_percent(self) -> float:

        if self.threshold_bytes <= 0:
            return 100.0

        return (
            self.logical_size_bytes
            / self.config.limit_bytes
            * 100.0
        )

    @property
    def threshold_reached(self) -> bool:

        return (
            self.logical_size_bytes
            >= self.threshold_bytes
        )

    @property
    def available_for_writes(self) -> bool:

        return (
            self.healthy
            and self.accepting_writes
            and self.config.enabled
            and not self.threshold_reached
        )


# ============================================================================
# DATABASE MANAGER
# ============================================================================


class DatabaseManager:
    """
    Central MongoDB infrastructure manager.

    Responsibilities:

        - Core database connection
        - Media shard connections
        - Shard routing
        - Health monitoring
        - Capacity monitoring
        - Media location registry
        - Core indexes
        - Runtime metrics
    """

    def __init__(
        self,
        config: Optional[
            DatabaseConfig
        ] = None,
    ) -> None:

        self.config = (
            config
            or DatabaseConfig.from_environment()
        )

        self.client: Optional[
            AsyncMongoClient
        ] = None

        self.database: Any = None

        self.initialized = False

        self._shards: dict[
            str,
            ShardRuntime
        ] = {}

        self._active_write_shard: Optional[
            str
        ] = None

        self._monitor_task: Optional[
            asyncio.Task
        ] = None

        self._monitor_lock = asyncio.Lock()

        self._metrics = {
            "reads": 0,
            "writes": 0,
            "errors": 0,
            "started_at": None,
        }

    # ========================================================================
    # CORE CLIENT
    # ========================================================================

    def create_client(
        self,
    ) -> AsyncMongoClient:

        if self.client is not None:
            return self.client

        self.config.validate()

        self.client = AsyncMongoClient(
            self.config.uri,
            serverSelectionTimeoutMS=(
                self.config
                .server_selection_timeout_ms
            ),
            connectTimeoutMS=(
                self.config
                .connect_timeout_ms
            ),
            socketTimeoutMS=(
                self.config
                .socket_timeout_ms
            ),
            appname=(
                self.config
                .application_name
            ),
        )

        self.database = self.client[
            self.config.database
        ]

        logger.info(
            "Core MongoDB client created: %s",
            self.config.sanitized_uri(),
        )

        logger.info(
            "Core MongoDB database selected: %s",
            self.config.database,
        )

        return self.client

    # ========================================================================
    # SHARD CLIENT
    # ========================================================================

    def _create_shard_client(
        self,
        runtime: ShardRuntime,
    ) -> AsyncMongoClient:

        if runtime.client is not None:
            return runtime.client

        config = runtime.config

        runtime.client = AsyncMongoClient(
            config.uri,
            serverSelectionTimeoutMS=(
                config.server_selection_timeout_ms
            ),
            connectTimeoutMS=(
                config.connect_timeout_ms
            ),
            socketTimeoutMS=(
                config.socket_timeout_ms
            ),
            appname=(
                config.application_name
            ),
        )

        runtime.database = (
            runtime.client[
                config.database
            ]
        )

        logger.info(
            "Media shard client created: "
            "%s -> %s",
            config.shard_id,
            config.sanitized_uri(),
        )

        return runtime.client

    # ========================================================================
    # DATABASE ACCESS
    # ========================================================================

    def get_database(
        self,
    ):

        if self.database is None:
            self.create_client()

        if self.database is None:

            raise RuntimeError(
                "Core MongoDB database is unavailable."
            )

        return self.database

    def get_core_database(
        self,
    ):

        return self.get_database()

    def get_shard_database(
        self,
        shard_id: str,
    ):

        runtime = self._shards.get(
            shard_id
        )

        if runtime is None:

            raise KeyError(
                f"Unknown media shard: {shard_id}"
            )

        if runtime.database is None:

            self._create_shard_client(
                runtime
            )

        if runtime.database is None:

            raise RuntimeError(
                f"Media shard unavailable: {shard_id}"
            )

        return runtime.database

    # ========================================================================
    # COLLECTION ACCESS
    # ========================================================================

    def collection(
        self,
        name: str,
    ):

        name = str(name).strip()

        if not name:

            raise ValueError(
                "Collection name cannot be empty."
            )

        return self.get_database()[name]

    def core_collection(
        self,
        name: str,
    ):

        return self.collection(
            name
        )

    def shard_collection(
        self,
        shard_id: str,
        name: str = MEDIA_COLLECTION,
    ):

        name = str(name).strip()

        if not name:

            raise ValueError(
                "Collection name cannot be empty."
            )

        return self.get_shard_database(
            shard_id
        )[name]

    # ========================================================================
    # SHARD INITIALIZATION
    # ========================================================================

    def _build_shard_runtimes(
        self,
    ) -> None:

        self._shards.clear()

        for shard_config in self.config.shards:

            self._shards[
                shard_config.shard_id
            ] = ShardRuntime(
                config=shard_config
            )

    # ========================================================================
    # INDEXES
    # ========================================================================

    async def initialize_core_indexes(
        self,
    ) -> None:

        db = self.get_database()

        users = db["users"]

        await users.create_index(
            [
                (
                    "telegram_user_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_users_telegram_user_id",
        )

        groups = db["groups"]

        await groups.create_index(
            [
                (
                    "telegram_chat_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_groups_telegram_chat_id",
        )

        premium = db["premium"]

        await premium.create_index(
            [
                (
                    "telegram_user_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_premium_user",
        )

        verification = db[
            "verification"
        ]

        await verification.create_index(
            [
                (
                    "telegram_user_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_verification_user",
        )

        referrals = db[
            "referrals"
        ]

        await referrals.create_index(
            [
                (
                    "telegram_user_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_referral_user",
        )

        settings = db[
            "settings"
        ]

        await settings.create_index(
            [
                (
                    "scope",
                    ASCENDING,
                ),
                (
                    "scope_id",
                    ASCENDING,
                ),
            ],
            unique=True,
            name="uq_settings_scope",
        )

        bot_state = db[
            "bot_state"
        ]

        await bot_state.create_index(
            [
                (
                    "key",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_bot_state_key",
        )

        locations = db[
            MEDIA_LOCATION_COLLECTION
        ]

        await locations.create_index(
            [
                (
                    "media_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_media_location_media_id",
        )

        await locations.create_index(
            [
                (
                    "shard_id",
                    ASCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ],
            name="ix_media_location_shard",
        )

        await locations.create_index(
            [
                (
                    "telegram_file_id",
                    ASCENDING,
                )
            ],
            unique=True,
            sparse=True,
            name="uq_media_location_file_id",
        )

        registry = db[
            SHARD_REGISTRY_COLLECTION
        ]

        await registry.create_index(
            [
                (
                    "shard_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_shard_registry_id",
        )

        monitoring = db[
            SHARD_MONITORING_COLLECTION
        ]

        await monitoring.create_index(
            [
                (
                    "shard_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_shard_monitoring_id",
        )

        logger.info(
            "Core MongoDB indexes initialized."
        )

    async def initialize_shard_indexes(
        self,
        runtime: ShardRuntime,
    ) -> None:

        collection = self.shard_collection(
            runtime.shard_id,
            MEDIA_COLLECTION,
        )

        await collection.create_index(
            [
                (
                    "media_id",
                    ASCENDING,
                )
            ],
            unique=True,
            name="uq_media_id",
        )

        await collection.create_index(
            [
                (
                    "telegram_file_id",
                    ASCENDING,
                )
            ],
            unique=True,
            sparse=True,
            name="uq_telegram_file_id",
        )

        await collection.create_index(
            [
                (
                    "movie_id",
                    ASCENDING,
                ),
                (
                    "created_at",
                    DESCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ],
            name="ix_movie_created_media",
        )

        await collection.create_index(
            [
                (
                    "episode_id",
                    ASCENDING,
                ),
                (
                    "created_at",
                    DESCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ],
            name="ix_episode_created_media",
        )

        await collection.create_index(
            [
                (
                    "series_id",
                    ASCENDING,
                ),
                (
                    "created_at",
                    DESCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ],
            name="ix_series_created_media",
        )

        await collection.create_index(
            [
                (
                    "filename",
                    ASCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ],
            name="ix_filename_media",
        )

        logger.info(
            "Media indexes initialized: %s",
            runtime.shard_id,
        )

    # ========================================================================
    # SHARD REGISTRY
    # ========================================================================

    async def _register_shard(
        self,
        runtime: ShardRuntime,
    ) -> None:

        collection = self.core_collection(
            SHARD_REGISTRY_COLLECTION
        )

        await collection.update_one(
            {
                "shard_id":
                    runtime.shard_id
            },
            {
                "$set": {
                    "shard_id":
                        runtime.shard_id,
                    "number":
                        runtime.config.number,
                    "database":
                        runtime.config.database,
                    "limit_mb":
                        runtime.config.limit_mb,
                    "threshold_percent":
                        runtime.config.threshold_percent,
                    "enabled":
                        runtime.config.enabled,
                    "updated_at":
                        utcnow(),
                },
                "$setOnInsert": {
                    "created_at":
                        utcnow(),
                },
            },
            upsert=True,
        )

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def _check_shard_health(
        self,
        runtime: ShardRuntime,
    ) -> bool:

        started = time.perf_counter()

        try:

            client = (
                self._create_shard_client(
                    runtime
                )
            )

            await client.admin.command(
                "ping"
            )

            latency = (
                time.perf_counter()
                - started
            ) * 1000

            runtime.healthy = True

            runtime.accepting_writes = (
                not runtime.threshold_reached
            )

            runtime.recovering = False

            runtime.failure_reason = None

            runtime.last_success = utcnow()

            runtime.last_latency_ms = (
                latency
            )

            runtime.total_latency_ms += (
                latency
            )

            return True

        except Exception as exc:

            runtime.healthy = False

            runtime.accepting_writes = False

            runtime.recovering = True

            runtime.last_failure = utcnow()

            runtime.failure_reason = (
                str(exc)
            )

            runtime.errors += 1

            self._metrics[
                "errors"
            ] += 1

            logger.warning(
                "Media shard unhealthy: %s: %s",
                runtime.shard_id,
                exc,
            )

            return False

    async def health_check(
        self,
        *,
        raise_on_error: bool = False,
    ) -> bool:

        try:

            client = (
                self.create_client()
            )

            started = time.perf_counter()

            await client.admin.command(
                "ping"
            )

            latency = (
                time.perf_counter()
                - started
            ) * 1000

            self._metrics[
                "last_core_latency_ms"
            ] = latency

            self._metrics[
                "last_core_success"
            ] = utcnow()

            return True

        except Exception:

            self._metrics[
                "errors"
            ] += 1

            self._metrics[
                "last_core_failure"
            ] = utcnow()

            if raise_on_error:
                raise

            logger.exception(
                "Core MongoDB health check failed."
            )

            return False

    async def ping(
        self,
    ) -> bool:

        return await self.health_check()

    async def is_healthy(
        self,
    ) -> bool:

        return await self.health_check()

    # ========================================================================
    # CAPACITY
    # ========================================================================

    async def refresh_shard_capacity(
        self,
        runtime: ShardRuntime,
    ) -> None:

        started = time.perf_counter()

        try:

            db = self.get_shard_database(
                runtime.shard_id
            )

            stats = await db.command(
                {
                    "dbStats": 1
                }
            )

            logical_size = int(
                stats.get(
                    "dataSize",
                    0,
                )
                or 0
            )

            document_count = 0

            try:

                collection_stats = (
                    await db[
                        MEDIA_COLLECTION
                    ].estimated_document_count()
                )

                document_count = int(
                    collection_stats
                )

            except Exception:

                document_count = 0

            runtime.logical_size_bytes = (
                logical_size
            )

            runtime.document_count = (
                document_count
            )

            runtime.last_capacity_check = (
                utcnow()
            )

            runtime.last_latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            if runtime.threshold_reached:

                runtime.accepting_writes = False

                logger.warning(
                    "Media shard capacity threshold reached: "
                    "%s %.2f%%",
                    runtime.shard_id,
                    runtime.utilization_percent,
                )

            elif runtime.healthy:

                runtime.accepting_writes = True

        except Exception as exc:

            runtime.errors += 1

            self._metrics[
                "errors"
            ] += 1

            runtime.failure_reason = (
                str(exc)
            )

            logger.warning(
                "Unable to inspect capacity for %s: %s",
                runtime.shard_id,
                exc,
            )

    # ========================================================================
    # ACTIVE WRITE SHARD
    # ========================================================================

    async def refresh_active_write_shard(
        self,
    ) -> Optional[str]:

        async with self._monitor_lock:

            candidates = [
                runtime
                for runtime
                in self._shards.values()
                if runtime.available_for_writes
            ]

            candidates.sort(
                key=lambda item:
                    (
                        item.config.number,
                        item.logical_size_bytes,
                    )
            )

            self._active_write_shard = (
                candidates[0].shard_id
                if candidates
                else None
            )

            return (
                self._active_write_shard
            )

    def active_write_shard(
        self,
    ) -> Optional[str]:

        return self._active_write_shard

    # ========================================================================
    # MEDIA ROUTING
    # ========================================================================

    async def get_write_shard(
        self,
    ) -> ShardRuntime:

        await self.refresh_active_write_shard()

        if (
            self._active_write_shard
            is not None
        ):

            return self._shards[
                self._active_write_shard
            ]

        # Force a health/capacity refresh
        # before declaring the pool exhausted.

        for runtime in sorted(
            self._shards.values(),
            key=lambda item:
                item.config.number,
        ):

            if not runtime.config.enabled:
                continue

            await self._check_shard_health(
                runtime
            )

            if runtime.healthy:

                await self.refresh_shard_capacity(
                    runtime
                )

        await self.refresh_active_write_shard()

        if (
            self._active_write_shard
            is not None
        ):

            return self._shards[
                self._active_write_shard
            ]

        raise RuntimeError(
            "No healthy media MongoDB shard "
            "is currently available for writes."
        )

    # ========================================================================
    # MEDIA ID
    # ========================================================================

    @staticmethod
    def new_media_id() -> str:

        return uuid.uuid4().hex

    # ========================================================================
    # MEDIA WRITE
    # ========================================================================

    async def insert_media(
        self,
        document: dict[str, Any],
    ) -> dict[str, Any]:

        runtime = await self.get_write_shard()

        media_id = (
            document.get(
                "media_id"
            )
            or self.new_media_id()
        )

        telegram_file_id = document.get(
            "telegram_file_id"
        )

        now = utcnow()

        record = dict(
            document
        )

        record[
            "media_id"
        ] = media_id

        record[
            "created_at"
        ] = record.get(
            "created_at",
            now,
        )

        record[
            "updated_at"
        ] = now

        record[
            "shard_id"
        ] = runtime.shard_id

        # Actual media bytes NEVER enter this document.

        forbidden = {
            "file_bytes",
            "media_bytes",
            "content",
            "binary",
            "data",
            "blob",
            "file_content",
        }

        for field_name in forbidden:

            if field_name in record:

                raise ValueError(
                    "Media documents may contain metadata only. "
                    f"Remove field: {field_name}"
                )

        collection = self.shard_collection(
            runtime.shard_id
        )

        started = time.perf_counter()

        try:

            await collection.insert_one(
                record
            )

            runtime.writes += 1

            self._metrics[
                "writes"
            ] += 1

            runtime.last_latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            # Registry is written ONLY after
            # the shard write succeeds.

            location = {
                "media_id":
                    media_id,
                "shard_id":
                    runtime.shard_id,
                "database":
                    runtime.config.database,
                "collection":
                    MEDIA_COLLECTION,
                "telegram_file_id":
                    telegram_file_id,
                "created_at":
                    now,
                "updated_at":
                    now,
                "status":
                    "active",
            }

            try:

                await self.core_collection(
                    MEDIA_LOCATION_COLLECTION
                ).insert_one(
                    location
                )

            except DuplicateKeyError:

                # Registry collision should never
                # silently create an inconsistent
                # location.

                await collection.delete_one(
                    {
                        "media_id":
                            media_id
                    }
                )

                raise

            await self.refresh_shard_capacity(
                runtime
            )

            await self.refresh_active_write_shard()

            return record

        except Exception as exc:

            runtime.errors += 1

            self._metrics[
                "errors"
            ] += 1

            # Duplicate file_id means this is
            # not a transient shard failure.

            if isinstance(
                exc,
                DuplicateKeyError,
            ):

                raise

            # Connection/server failures disable
            # new writes to this shard.

            runtime.healthy = False

            runtime.accepting_writes = False

            runtime.recovering = True

            runtime.last_failure = utcnow()

            runtime.failure_reason = (
                str(exc)
            )

            raise

    # ========================================================================
    # MEDIA LOCATION
    # ========================================================================

    async def get_media_location(
        self,
        media_id: str,
    ) -> Optional[
        dict[str, Any]
    ]:

        self._metrics[
            "reads"
        ] += 1

        return await self.core_collection(
            MEDIA_LOCATION_COLLECTION
        ).find_one(
            {
                "media_id":
                    media_id
            }
        )

    async def get_media_by_file_id(
        self,
        telegram_file_id: str,
    ) -> Optional[
        dict[str, Any]
    ]:

        self._metrics[
            "reads"
        ] += 1

        return await self.core_collection(
            MEDIA_LOCATION_COLLECTION
        ).find_one(
            {
                "telegram_file_id":
                    telegram_file_id
            }
        )

    async def get_media(
        self,
        media_id: str,
    ) -> Optional[
        dict[str, Any]
    ]:

        location = await (
            self.get_media_location(
                media_id
            )
        )

        if not location:
            return None

        shard_id = location[
            "shard_id"
        ]

        document = await self.shard_collection(
            shard_id
        ).find_one(
            {
                "media_id":
                    media_id
            }
        )

        return document

    # ========================================================================
    # MEDIA DELETE
    # ========================================================================

    async def delete_media(
        self,
        media_id: str,
    ) -> bool:

        location = await (
            self.get_media_location(
                media_id
            )
        )

        if not location:
            return False

        shard_id = location[
            "shard_id"
        ]

        result = await self.shard_collection(
            shard_id
        ).delete_one(
            {
                "media_id":
                    media_id
            }
        )

        if result.deleted_count:

            await self.core_collection(
                MEDIA_LOCATION_COLLECTION
            ).update_one(
                {
                    "media_id":
                        media_id
                },
                {
                    "$set": {
                        "status":
                            "deleted",
                        "updated_at":
                            utcnow(),
                    }
                },
            )

            return True

        return False

    # ========================================================================
    # SHARD SEARCH
    # ========================================================================

    async def search_media_shard(
        self,
        shard_id: str,
        query: dict[str, Any],
        *,
        limit: int = 50,
        sort: Optional[
            list[tuple[str, int]]
        ] = None,
    ) -> list[
        dict[str, Any]
    ]:

        runtime = self._shards.get(
            shard_id
        )

        if runtime is None:

            raise KeyError(
                f"Unknown media shard: {shard_id}"
            )

        if limit <= 0:
            return []

        limit = min(
            limit,
            500,
        )

        if sort is None:

            sort = [
                (
                    "created_at",
                    DESCENDING,
                ),
                (
                    "media_id",
                    ASCENDING,
                ),
            ]

        started = time.perf_counter()

        try:

            cursor = (
                self.shard_collection(
                    shard_id
                )
                .find(query)
                .sort(sort)
                .limit(limit)
            )

            results = []

            async for document in cursor:

                results.append(
                    document
                )

            runtime.reads += 1

            self._metrics[
                "reads"
            ] += 1

            runtime.last_latency_ms = (
                time.perf_counter()
                - started
            ) * 1000

            return results

        except Exception as exc:

            runtime.errors += 1

            self._metrics[
                "errors"
            ] += 1

            raise exc

    # ========================================================================
    # SHARD STATUS
    # ========================================================================

    async def refresh_shard(
        self,
        runtime: ShardRuntime,
    ) -> None:

        async with runtime.lock:

            healthy = (
                await self._check_shard_health(
                    runtime
                )
            )

            if healthy:

                await self.refresh_shard_capacity(
                    runtime
                )

                await self._register_shard(
                    runtime
                )

                runtime.accepting_writes = (
                    not runtime.threshold_reached
                )

    async def refresh_all_shards(
        self,
    ) -> None:

        tasks = [
            self.refresh_shard(
                runtime
            )
            for runtime
            in self._shards.values()
            if runtime.config.enabled
        ]

        if tasks:

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        await self.refresh_active_write_shard()

    # ========================================================================
    # MONITORING LOOP
    # ========================================================================

    async def _monitor_loop(
        self,
    ) -> None:

        while True:

            try:

                await self.refresh_all_shards()

            except asyncio.CancelledError:

                raise

            except Exception:

                logger.exception(
                    "MongoDB shard monitoring cycle failed."
                )

            try:

                await asyncio.sleep(
                    max(
                        5,
                        self.config.monitor_interval_seconds,
                    )
                )

            except asyncio.CancelledError:

                raise

    def start_monitoring(
        self,
    ) -> None:

        if self._monitor_task is not None:

            if not self._monitor_task.done():
                return

        try:

            self._monitor_task = (
                asyncio.create_task(
                    self._monitor_loop(),
                    name=(
                        "downtown-villa-mongodb-monitor"
                    ),
                )
            )

        except RuntimeError:

            logger.warning(
                "No running event loop; "
                "MongoDB monitoring will start during initialize()."
            )

    async def stop_monitoring(
        self,
    ) -> None:

        task = self._monitor_task

        self._monitor_task = None

        if task is None:
            return

        if task.done():
            return

        task.cancel()

        try:

            await task

        except asyncio.CancelledError:

            pass

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    async def initialize(
        self,
    ) -> "DatabaseManager":

        if self.initialized:
            return self

        self.config.validate()

        self.create_client()

        self._build_shard_runtimes()

        core_healthy = await self.health_check(
            raise_on_error=True
        )

        if not core_healthy:

            raise RuntimeError(
                "Core MongoDB is unavailable."
            )

        await self.initialize_core_indexes()

        # Media shards are optional at startup.
        #
        # The bot can run with only CORE DB.
        # Media writes become available as shards
        # recover.

        await self.refresh_all_shards()

        self._metrics[
            "started_at"
        ] = utcnow()

        self.initialized = True

        self.start_monitoring()

        logger.info(
            "MongoDB architecture initialized. "
            "Core=%s MediaShards=%d ActiveWriteShard=%s",
            self.config.database,
            len(self._shards),
            self._active_write_shard,
        )

        return self

    # ========================================================================
    # TRANSACTION
    # ========================================================================

    @asynccontextmanager
    async def transaction(
        self,
    ) -> AsyncIterator[Any]:

        if self.client is None:

            self.create_client()

        if self.client is None:

            raise RuntimeError(
                "MongoDB client is unavailable."
            )

        async with (
            await self.client.start_session()
        ) as session:

            async with session.start_transaction():

                yield session

    # ========================================================================
    # SESSION
    # ========================================================================

    async def start_session(
        self,
    ):

        if self.client is None:

            self.create_client()

        if self.client is None:

            raise RuntimeError(
                "MongoDB client is unavailable."
            )

        return await (
            self.client.start_session()
        )

    # ========================================================================
    # COMMAND
    # ========================================================================

    async def command(
        self,
        command: Any,
    ) -> Any:

        return await self.get_database().command(
            command
        )

    # ========================================================================
    # METRICS
    # ========================================================================

    def _runtime_status(
        self,
        runtime: ShardRuntime,
    ) -> dict[str, Any]:

        return {
            "shard_id":
                runtime.shard_id,

            "number":
                runtime.config.number,

            "database":
                runtime.config.database,

            "enabled":
                runtime.config.enabled,

            "healthy":
                runtime.healthy,

            "accepting_writes":
                runtime.accepting_writes,

            "recovering":
                runtime.recovering,

            "capacity_limit_mb":
                runtime.config.limit_mb,

            "threshold_percent":
                runtime.config.threshold_percent,

            "logical_size_bytes":
                runtime.logical_size_bytes,

            "logical_size_mb":
                round(
                    runtime.logical_size_bytes
                    / 1024
                    / 1024,
                    3,
                ),

            "document_count":
                runtime.document_count,

            "utilization_percent":
                round(
                    runtime.utilization_percent,
                    3,
                ),

            "threshold_reached":
                runtime.threshold_reached,

            "reads":
                runtime.reads,

            "writes":
                runtime.writes,

            "errors":
                runtime.errors,

            "last_latency_ms":
                round(
                    runtime.last_latency_ms,
                    3,
                ),

            "last_success":
                runtime.last_success,

            "last_failure":
                runtime.last_failure,

            "last_capacity_check":
                runtime.last_capacity_check,

            "failure_reason":
                runtime.failure_reason,

            "recovery_attempts":
                runtime.recovery_attempts,
        }

    def status(
        self,
    ) -> dict[str, Any]:

        shards = {
            shard_id:
                self._runtime_status(
                    runtime
                )
            for shard_id, runtime
            in self._shards.items()
        }

        return {
            "provider":
                "mongodb",

            "architecture":
                "core-plus-media-shards",

            "initialized":
                self.initialized,

            "core": {
                "database":
                    self.config.database,

                "healthy":
                    self.initialized,

                "client_created":
                    self.client is not None,

                "uri":
                    self.config.sanitized_uri(),

                "last_latency_ms":
                    self._metrics.get(
                        "last_core_latency_ms"
                    ),

                "last_success":
                    self._metrics.get(
                        "last_core_success"
                    ),

                "last_failure":
                    self._metrics.get(
                        "last_core_failure"
                    ),
            },

            "media": {
                "shard_count":
                    len(self._shards),

                "active_write_shard":
                    self._active_write_shard,

                "shards":
                    shards,
            },

            "metrics":
                dict(
                    self._metrics
                ),
        }

    # ========================================================================
    # SHARD REGISTRY STATUS
    # ========================================================================

    async def persist_monitoring_status(
        self,
    ) -> None:

        collection = self.core_collection(
            SHARD_MONITORING_COLLECTION
        )

        operations = []

        for runtime in self._shards.values():

            operations.append(
                {
                    "shard_id":
                        runtime.shard_id,

                    "healthy":
                        runtime.healthy,

                    "accepting_writes":
                        runtime.accepting_writes,

                    "recovering":
                        runtime.recovering,

                    "logical_size_bytes":
                        runtime.logical_size_bytes,

                    "document_count":
                        runtime.document_count,

                    "reads":
                        runtime.reads,

                    "writes":
                        runtime.writes,

                    "errors":
                        runtime.errors,

                    "latency_ms":
                        runtime.last_latency_ms,

                    "last_success":
                        runtime.last_success,

                    "last_failure":
                        runtime.last_failure,

                    "updated_at":
                        utcnow(),
                }
            )

        for status_document in operations:

            await collection.update_one(
                {
                    "shard_id":
                        status_document[
                            "shard_id"
                        ]
                },
                {
                    "$set":
                        status_document
                },
                upsert=True,
            )

    # ========================================================================
    # SHARD ACCESSORS
    # ========================================================================

    def shard_ids(
        self,
    ) -> list[str]:

        return [
            runtime.shard_id
            for runtime
            in sorted(
                self._shards.values(),
                key=lambda item:
                    item.config.number,
            )
        ]

    def shard_count(
        self,
    ) -> int:

        return len(
            self._shards
        )

    def get_shard(
        self,
        shard_id: str,
    ) -> Optional[
        ShardRuntime
    ]:

        return self._shards.get(
            shard_id
        )

    # ========================================================================
    # CLOSE
    # ========================================================================

    async def close(
        self,
    ) -> None:

        await self.stop_monitoring()

        clients = []

        if self.client is not None:

            clients.append(
                self.client
            )

        for runtime in self._shards.values():

            if runtime.client is not None:

                clients.append(
                    runtime.client
                )

        for client in clients:

            try:

                await client.close()

            except Exception:

                logger.exception(
                    "MongoDB client close failed."
                )

        self.client = None

        self.database = None

        for runtime in self._shards.values():

            runtime.client = None

            runtime.database = None

            runtime.healthy = False

            runtime.accepting_writes = False

        self._shards.clear()

        self._active_write_shard = None

        self.initialized = False

        logger.info(
            "MongoDB architecture shut down."
        )

    async def disconnect(
        self,
    ) -> None:

        await self.close()

    async def shutdown(
        self,
    ) -> None:

        await self.close()


# ============================================================================
# GLOBAL MANAGER
# ============================================================================


_database_manager: Optional[
    DatabaseManager
] = None


def get_database_manager(
    app: Any = None,
) -> Optional[
    DatabaseManager
]:

    global _database_manager

    if app is not None:

        for attribute in (
            "db",
            "database",
        ):

            existing = getattr(
                app,
                attribute,
                None,
            )

            if isinstance(
                existing,
                DatabaseManager,
            ):

                _database_manager = (
                    existing
                )

                return existing

    return _database_manager


def set_database_manager(
    manager: DatabaseManager,
    app: Any = None,
) -> DatabaseManager:

    global _database_manager

    _database_manager = manager

    if app is not None:

        try:

            setattr(
                app,
                "db",
                manager,
            )

        except Exception:

            logger.debug(
                "Unable to attach database manager.",
                exc_info=True,
            )

    return manager


# ============================================================================
# INITIALIZATION HELPERS
# ============================================================================


async def initialize(
    app: Any = None,
    config: Any = None,
) -> DatabaseManager:

    existing = (
        get_database_manager(
            app
        )
    )

    if existing is not None:

        if not existing.initialized:

            await existing.initialize()

        return existing

    if config is None:

        config = (
            getattr(
                app,
                "config",
                None,
            )
            if app is not None
            else None
        )

    database_config = (
        DatabaseConfig.from_config(
            config
        )
    )

    manager = DatabaseManager(
        database_config
    )

    await manager.initialize()

    set_database_manager(
        manager,
        app,
    )

    return manager


async def init_database(
    app: Any = None,
    config: Any = None,
) -> DatabaseManager:

    return await initialize(
        app=app,
        config=config,
    )


# ============================================================================
# SHORTCUTS
# ============================================================================


def get_database(
    app: Any = None,
):

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return manager.get_database()


def get_collection(
    name: str,
    app: Any = None,
):

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return manager.collection(
        name
    )


def get_shard_collection(
    shard_id: str,
    name: str = MEDIA_COLLECTION,
    app: Any = None,
):

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return manager.shard_collection(
        shard_id,
        name,
    )


# ============================================================================
# DRIVER HELPERS
# ============================================================================


def is_mongodb_available() -> bool:

    return True


def is_sqlalchemy_available() -> bool:

    return False


def get_engine(
    app: Any = None,
):

    return None


def get_session_factory(
    app: Any = None,
):

    return None


# ============================================================================
# HEALTH SHORTCUTS
# ============================================================================


async def health_check(
    app: Any = None,
) -> bool:

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        return False

    return await manager.health_check()


async def ping(
    app: Any = None,
) -> bool:

    return await health_check(
        app
    )


# ============================================================================
# SHARD SHORTCUTS
# ============================================================================


async def get_write_shard(
    app: Any = None,
) -> ShardRuntime:

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return await manager.get_write_shard()


async def insert_media(
    document: dict[str, Any],
    app: Any = None,
) -> dict[str, Any]:

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return await manager.insert_media(
        document
    )


async def get_media(
    media_id: str,
    app: Any = None,
):

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return await manager.get_media(
        media_id
    )


async def get_media_location(
    media_id: str,
    app: Any = None,
):

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return await manager.get_media_location(
        media_id
    )
    # ========================================================================
    # Legacy user compatibility API
    # ========================================================================

    @property
    def users(self):
        return self.collection("users")

    async def is_user_exist(self, user_id: int) -> bool:
        document = await self.users.find_one(
            {"_id": int(user_id)},
            {"_id": 1},
        )
        return document is not None

    async def get_user(self, user_id: int):
        return await self.users.find_one(
            {"_id": int(user_id)}
        )

    async def add_user(self, user_id: int, **data):
        user_id = int(user_id)

        await self.users.update_one(
            {"_id": user_id},
            {
                "$set": data,
                "$setOnInsert": {
                    "user_id": user_id,
                },
            },
            upsert=True,
        )

        return await self.get_user(user_id)

    async def update_user(
        self,
        user_id: int,
        **data,
    ):
        await self.users.update_one(
            {"_id": int(user_id)},
            {"$set": data},
            upsert=True,
        )

        return await self.get_user(user_id)

    async def get_ban_status(
        self,
        user_id: int,
    ) -> bool:
        user = await self.get_user(user_id)

        if not user:
            return False

        return bool(
            user.get("is_banned", False)
            or user.get("banned", False)
        )

    async def set_ban_status(
        self,
        user_id: int,
        banned: bool,
    ):
        return await self.update_user(
            user_id,
            is_banned=bool(banned),
            banned=bool(banned),
        )


# ============================================================================
# SHUTDOWN
# ============================================================================


async def close(
    app: Any = None,
) -> None:

    global _database_manager

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:
        return

    await manager.close()

    if manager is _database_manager:

        _database_manager = None

    if app is not None:

        try:

            if getattr(
                app,
                "db",
                None,
            ) is manager:

                setattr(
                    app,
                    "db",
                    None,
                )

        except Exception:

            logger.debug(
                "Unable to clear app database reference.",
                exc_info=True,
            )


async def disconnect(
    app: Any = None,
) -> None:

    await close(
        app
    )


# ============================================================================
# STATUS
# ============================================================================


async def status(
    app: Any = None,
) -> dict[str, Any]:

    manager = (
        get_database_manager(
            app
        )
    )

    if manager is None:

        return {
            "provider":
                "mongodb",

            "initialized":
                False,

            "healthy":
                False,

            "core":
                None,

            "media":
                {
                    "shard_count":
                        0,

                    "active_write_shard":
                        None,

                    "shards":
                        {},
                },
        }

    result = manager.status()

    result[
        "healthy"
    ] = await manager.health_check()

    return result


# ============================================================================
# RESET
# ============================================================================


async def reset_manager() -> None:

    global _database_manager

    if _database_manager is not None:

        await _database_manager.close()

    _database_manager = None


# ============================================================================
# EXPORTS
# ============================================================================


__all__ = [
    "CORE_SHARD_ID",

    "MEDIA_COLLECTION",

    "MEDIA_LOCATION_COLLECTION",

    "SHARD_REGISTRY_COLLECTION",

    "SHARD_MONITORING_COLLECTION",

    "DatabaseConfig",

    "MediaShardConfig",

    "ShardRuntime",

    "DatabaseManager",

    "get_database_manager",

    "set_database_manager",

    "initialize",

    "init_database",

    "get_database",

    "get_collection",

    "get_shard_collection",

    "get_write_shard",

    "insert_media",

    "get_media",

    "get_media_location",

    "health_check",

    "ping",

    "close",

    "disconnect",

    "is_mongodb_available",

    "is_sqlalchemy_available",

    "get_engine",

    "get_session_factory",

    "status",

    "reset_manager",
]
