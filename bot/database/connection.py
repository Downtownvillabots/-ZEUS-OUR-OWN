
"""
bot.database.connection

MongoDB connection and lifecycle management.

Environment:
    MONGO_URI
    MONGO_DATABASE

Optional:
    MONGO_SERVER_SELECTION_TIMEOUT_MS
    MONGO_CONNECT_TIMEOUT_MS
    MONGO_SOCKET_TIMEOUT_MS
    MONGO_APP_NAME

The application owns one DatabaseManager instance. Repositories access
MongoDB through that manager rather than creating their own clients.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional
from contextlib import asynccontextmanager

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError, ServerSelectionTimeoutError

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_DATABASE_NAME = "telegram_bot"

DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 10_000

DEFAULT_CONNECT_TIMEOUT_MS = 10_000

DEFAULT_SOCKET_TIMEOUT_MS = 30_000

DEFAULT_APP_NAME = "telegram-bot"


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class DatabaseConfig:
    """
    MongoDB connection configuration.
    """

    uri: str = ""

    database: str = DEFAULT_DATABASE_NAME

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

    @classmethod
    def from_environment(
        cls,
    ) -> "DatabaseConfig":
        """
        Load MongoDB configuration from environment variables.
        """

        uri = (
            os.getenv("MONGO_URI")
            or os.getenv("MONGODB_URI")
            or ""
        ).strip()

        database = (
            os.getenv("MONGO_DATABASE")
            or os.getenv("MONGODB_DATABASE")
            or DEFAULT_DATABASE_NAME
        ).strip()

        return cls(
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
            application_name=(
                os.getenv(
                    "MONGO_APP_NAME"
                )
                or DEFAULT_APP_NAME
            ),
        )

    @classmethod
    def from_config(
        cls,
        config: Any,
    ) -> "DatabaseConfig":
        """
        Create MongoDB configuration from Settings, a dict, or None.
        """

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
            or DEFAULT_DATABASE_NAME
        )

        return cls(
            uri=str(uri).strip(),
            database=str(database).strip(),
            server_selection_timeout_ms=_safe_int(
                getter(
                    "mongo_server_selection_timeout_ms",
                    DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
                ),
                DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
            ),
            connect_timeout_ms=_safe_int(
                getter(
                    "mongo_connect_timeout_ms",
                    DEFAULT_CONNECT_TIMEOUT_MS,
                ),
                DEFAULT_CONNECT_TIMEOUT_MS,
            ),
            socket_timeout_ms=_safe_int(
                getter(
                    "mongo_socket_timeout_ms",
                    DEFAULT_SOCKET_TIMEOUT_MS,
                ),
                DEFAULT_SOCKET_TIMEOUT_MS,
            ),
            application_name=str(
                getter(
                    "mongo_app_name",
                    DEFAULT_APP_NAME,
                )
            ),
        )

    def validate(
        self,
    ) -> None:
        """
        Validate required MongoDB configuration.
        """

        if not self.uri:

            raise RuntimeError(
                "MONGO_URI is not configured."
            )

        if not self.database:

            raise RuntimeError(
                "MONGO_DATABASE is not configured."
            )

    def sanitized_uri(
        self,
    ) -> str:
        """
        Return a URI safe for logging.

        Credentials are never logged.
        """

        value = self.uri

        if not value:

            return "<not-configured>"

        try:

            if "@" not in value:

                return value

            scheme, remainder = (
                value.split(
                    "://",
                    1,
                )
            )

            if "@" not in remainder:

                return value

            credentials, host = (
                remainder.split(
                    "@",
                    1,
                )
            )

            if ":" in credentials:

                username = (
                    credentials.split(
                        ":",
                        1,
                    )[0]
                )

                credentials = (
                    username
                    + ":***"
                )

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
# Helpers
# ============================================================================


def _safe_int(
    value: Any,
    default: int,
) -> int:
    """
    Safely convert a value to int.
    """

    try:

        return int(value)

    except (
        TypeError,
        ValueError,
    ):

        return default


# ============================================================================
# Database manager
# ============================================================================


class DatabaseManager:
    """
    Owns the MongoDB AsyncMongoClient and database handle.

    The manager deliberately exposes both:

        manager.client
        manager.database

    so repository migration can happen incrementally.
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

        self.database = None

        self.initialized = False

    # ========================================================================
    # Client creation
    # ========================================================================

    def create_client(
        self,
    ) -> AsyncMongoClient:
        """
        Create the MongoDB async client.

        The client is created once and reused for the application's
        lifetime.
        """

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

        self.database = (
            self.client[
                self.config.database
            ]
        )

        logger.info(
            "MongoDB client created: %s",
            self.config.sanitized_uri(),
        )

        logger.info(
            "MongoDB database selected: %s",
            self.config.database,
        )

        return self.client

    # ========================================================================
    # Database handle
    # ========================================================================

    def get_database(
        self,
    ):
        """
        Return the selected MongoDB database.
        """

        if self.database is None:

            self.create_client()

        if self.database is None:

            raise RuntimeError(
                "MongoDB database is unavailable."
            )

        return self.database

    # ========================================================================
    # Collection
    # ========================================================================

    def collection(
        self,
        name: str,
    ):
        """
        Return a MongoDB collection.
        """

        collection_name = (
            str(name)
            .strip()
        )

        if not collection_name:

            raise ValueError(
                "Collection name cannot be empty."
            )

        return self.get_database()[
            collection_name
        ]

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(
        self,
    ) -> "DatabaseManager":
        """
        Create the client and verify connectivity with ping.
        """

        if self.initialized:

            return self

        self.create_client()

        await self.health_check(
            raise_on_error=True
        )

        self.initialized = True

        logger.info(
            "MongoDB database manager initialized."
        )

        return self

    # ========================================================================
    # Health
    # ========================================================================

    async def health_check(
        self,
        *,
        raise_on_error: bool = False,
    ) -> bool:
        """
        Ping MongoDB.

        MongoDB's ping command is the authoritative connectivity check.
        """

        try:

            client = (
                self.create_client()
            )

            await client.admin.command(
                "ping"
            )

            return True

        except (
            ServerSelectionTimeoutError,
            PyMongoError,
            OSError,
        ):

            logger.exception(
                "MongoDB health check failed."
            )

            if raise_on_error:

                raise

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
    # Transaction compatibility
    # ========================================================================

    @asynccontextmanager
    async def transaction(
        self,
    ) -> AsyncIterator[Any]:
        """
        Provide a MongoDB session/transaction context.

        MongoDB transactions require a deployment that supports them
        (for example Atlas replica sets).

        Repository migration should use this context when atomic
        multi-document operations are required.
        """

        if self.client is None:

            self.create_client()

        if self.client is None:

            raise RuntimeError(
                "MongoDB client is unavailable."
            )

        session = (
            await self.client.start_session()
        )

        try:

            async with session.start_transaction():

                yield session

        except Exception:

            try:

                await session.abort_transaction()

            except Exception:

                logger.debug(
                    "MongoDB transaction abort failed.",
                    exc_info=True,
                )

            raise

        finally:

            await session.end_session()

    # ========================================================================
    # Session
    # ========================================================================

    async def start_session(
        self,
    ):
        """
        Start a MongoDB session.

        Callers are responsible for ending it.
        """

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
    # Command
    # ========================================================================

    async def command(
        self,
        command: Any,
    ) -> Any:
        """
        Execute a database command.
        """

        return await self.get_database().command(
            command
        )

    # ========================================================================
    # Shutdown
    # ========================================================================

    async def close(
        self,
    ) -> None:
        """
        Close the MongoDB client.
        """

        if self.client is None:

            self.database = None

            self.initialized = False

            return

        try:

            await self.client.close()

        finally:

            self.client = None

            self.database = None

            self.initialized = False

        logger.info(
            "MongoDB client closed."
        )

    async def disconnect(
        self,
    ) -> None:

        await self.close()

    async def shutdown(
        self,
    ) -> None:

        await self.close()

    # ========================================================================
    # Status
    # ========================================================================

    def status(
        self,
    ) -> dict[str, Any]:
        """
        Return safe database status information.
        """

        return {
            "initialized": (
                self.initialized
            ),
            "client_created": (
                self.client is not None
            ),
            "database": (
                self.config.database
            ),
            "provider": "mongodb",
            "uri": (
                self.config.sanitized_uri()
            ),
        }


# ============================================================================
# Global manager
# ============================================================================


_database_manager: Optional[
    DatabaseManager
] = None


def get_database_manager(
    app: Any = None,
) -> Optional[
    DatabaseManager
]:
    """
    Retrieve the global/application DatabaseManager.
    """

    global _database_manager

    if app is not None:

        existing = getattr(
            app,
            "db",
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

        existing = getattr(
            app,
            "database",
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
    """
    Register the application's database manager.
    """

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
                "Unable to attach database manager to app.",
                exc_info=True,
            )

    return manager


# ============================================================================
# Initialization helpers
# ============================================================================


async def initialize(
    app: Any = None,
    config: Any = None,
) -> DatabaseManager:
    """
    Initialize MongoDB.
    """

    existing = (
        get_database_manager(app)
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
# MongoDB shortcuts
# ============================================================================


def get_database(
    app: Any = None,
):
    """
    Return the application's MongoDB database.
    """

    manager = (
        get_database_manager(app)
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
    """
    Return a named MongoDB collection.
    """

    manager = (
        get_database_manager(app)
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return manager.collection(
        name
    )


# ============================================================================
# Compatibility helpers
# ============================================================================


def is_mongodb_available() -> bool:
    """
    Report whether the MongoDB driver is installed.
    """

    return True


def is_sqlalchemy_available() -> bool:
    """
    Compatibility helper.

    SQLAlchemy is no longer the database driver for this connection layer.
    """

    return False


def get_engine(
    app: Any = None,
):
    """
    SQLAlchemy compatibility method.

    MongoDB has no SQLAlchemy engine.
    """

    return None


def get_session_factory(
    app: Any = None,
):
    """
    SQLAlchemy compatibility method.

    MongoDB uses collections and sessions instead.
    """

    return None


# ============================================================================
# Health shortcuts
# ============================================================================


async def health_check(
    app: Any = None,
) -> bool:

    manager = (
        get_database_manager(app)
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
# Shutdown shortcuts
# ============================================================================


async def close(
    app: Any = None,
) -> None:
    """
    Close the global MongoDB manager.
    """

    global _database_manager

    manager = (
        get_database_manager(app)
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
# Status
# ============================================================================


async def status(
    app: Any = None,
) -> dict[str, Any]:
    """
    Return safe database status.
    """

    manager = (
        get_database_manager(app)
    )

    if manager is None:

        return {
            "initialized": False,
            "healthy": False,
            "client_created": False,
            "database": None,
            "provider": "mongodb",
        }

    healthy = (
        await manager.health_check()
    )

    result = manager.status()

    result[
        "healthy"
    ] = healthy

    return result


# ============================================================================
# Reset
# ============================================================================


async def reset_manager() -> None:
    """
    Close and remove the global database manager.
    """

    global _database_manager

    if _database_manager is not None:

        await _database_manager.close()

    _database_manager = None


# ============================================================================
# Exports
# ============================================================================


__all__ = [
    "DatabaseConfig",
    "DatabaseManager",

    "get_database_manager",
    "set_database_manager",

    "initialize",
    "init_database",

    "get_database",
    "get_collection",

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

