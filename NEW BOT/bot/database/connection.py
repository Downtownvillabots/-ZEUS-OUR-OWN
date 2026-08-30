"""
bot.database.connection

Async PostgreSQL database connection and lifecycle management.

Responsibilities
----------------
- Database URL/configuration handling
- Async SQLAlchemy engine creation
- Session factory
- Transaction management
- Connection health checks
- Startup/shutdown lifecycle
- Pool configuration
- Safe application integration

Expected environment variables
-------------------------------
DATABASE_URL
DB_URL
DATABASE_HOST
DATABASE_PORT
DATABASE_NAME
DATABASE_USER
DATABASE_PASSWORD

Preferred production configuration:

    DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database

SQLite is supported for development/testing:

    sqlite+aiosqlite:///./data/bot.db

The application should use this module instead of creating database
connections in individual handlers/services.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_DB_HOST = "localhost"

DEFAULT_DB_PORT = 5432

DEFAULT_DB_NAME = "bot"

DEFAULT_DB_USER = "postgres"

DEFAULT_POOL_SIZE = 10

DEFAULT_MAX_OVERFLOW = 20

DEFAULT_POOL_TIMEOUT = 30

DEFAULT_POOL_RECYCLE = 1800

DEFAULT_CONNECT_TIMEOUT = 10

DEFAULT_ECHO = False


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class DatabaseConfig:
    """
    Database connection configuration.
    """

    url: Optional[str] = None

    host: str = DEFAULT_DB_HOST

    port: int = DEFAULT_DB_PORT

    name: str = DEFAULT_DB_NAME

    user: str = DEFAULT_DB_USER

    password: str = ""

    pool_size: int = DEFAULT_POOL_SIZE

    max_overflow: int = DEFAULT_MAX_OVERFLOW

    pool_timeout: int = DEFAULT_POOL_TIMEOUT

    pool_recycle: int = DEFAULT_POOL_RECYCLE

    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT

    echo: bool = DEFAULT_ECHO

    ssl: Optional[str] = None

    application_name: str = "telegram-bot"

    @classmethod
    def from_environment(
        cls,
    ) -> "DatabaseConfig":

        url = (
            os.getenv(
                "DATABASE_URL"
            )
            or os.getenv(
                "DB_URL"
            )
        )

        host = os.getenv(
            "DATABASE_HOST",
            DEFAULT_DB_HOST,
        )

        port = _int_env(
            "DATABASE_PORT",
            DEFAULT_DB_PORT,
        )

        name = os.getenv(
            "DATABASE_NAME",
            DEFAULT_DB_NAME,
        )

        user = os.getenv(
            "DATABASE_USER",
            DEFAULT_DB_USER,
        )

        password = os.getenv(
            "DATABASE_PASSWORD",
            "",
        )

        pool_size = _int_env(
            "DATABASE_POOL_SIZE",
            DEFAULT_POOL_SIZE,
        )

        max_overflow = _int_env(
            "DATABASE_MAX_OVERFLOW",
            DEFAULT_MAX_OVERFLOW,
        )

        pool_timeout = _int_env(
            "DATABASE_POOL_TIMEOUT",
            DEFAULT_POOL_TIMEOUT,
        )

        pool_recycle = _int_env(
            "DATABASE_POOL_RECYCLE",
            DEFAULT_POOL_RECYCLE,
        )

        connect_timeout = _int_env(
            "DATABASE_CONNECT_TIMEOUT",
            DEFAULT_CONNECT_TIMEOUT,
        )

        echo = _bool_env(
            "DATABASE_ECHO",
            DEFAULT_ECHO,
        )

        ssl = os.getenv(
            "DATABASE_SSL"
        )

        application_name = os.getenv(
            "DATABASE_APPLICATION_NAME",
            "telegram-bot",
        )

        return cls(
            url=url,
            host=host,
            port=port,
            name=name,
            user=user,
            password=password,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            connect_timeout=connect_timeout,
            echo=echo,
            ssl=ssl,
            application_name=application_name,
        )

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

            getter = lambda key, default=None: getattr(
                config,
                key,
                default,
            )

        url = (
            getter(
                "database_url"
            )
            or getter(
                "db_url"
            )
            or getter(
                "url"
            )
        )

        return cls(
            url=url,
            host=getter(
                "database_host",
                getter(
                    "host",
                    DEFAULT_DB_HOST,
                ),
            ),
            port=_safe_int(
                getter(
                    "database_port",
                    getter(
                        "port",
                        DEFAULT_DB_PORT,
                    ),
                ),
                DEFAULT_DB_PORT,
            ),
            name=getter(
                "database_name",
                getter(
                    "name",
                    DEFAULT_DB_NAME,
                ),
            ),
            user=getter(
                "database_user",
                getter(
                    "user",
                    DEFAULT_DB_USER,
                ),
            ),
            password=getter(
                "database_password",
                getter(
                    "password",
                    "",
                ),
            ),
            pool_size=_safe_int(
                getter(
                    "database_pool_size",
                    DEFAULT_POOL_SIZE,
                ),
                DEFAULT_POOL_SIZE,
            ),
            max_overflow=_safe_int(
                getter(
                    "database_max_overflow",
                    DEFAULT_MAX_OVERFLOW,
                ),
                DEFAULT_MAX_OVERFLOW,
            ),
            pool_timeout=_safe_int(
                getter(
                    "database_pool_timeout",
                    DEFAULT_POOL_TIMEOUT,
                ),
                DEFAULT_POOL_TIMEOUT,
            ),
            pool_recycle=_safe_int(
                getter(
                    "database_pool_recycle",
                    DEFAULT_POOL_RECYCLE,
                ),
                DEFAULT_POOL_RECYCLE,
            ),
            connect_timeout=_safe_int(
                getter(
                    "database_connect_timeout",
                    DEFAULT_CONNECT_TIMEOUT,
                ),
                DEFAULT_CONNECT_TIMEOUT,
            ),
            echo=_safe_bool(
                getter(
                    "database_echo",
                    DEFAULT_ECHO,
                ),
                DEFAULT_ECHO,
            ),
            ssl=getter(
                "database_ssl",
                getter(
                    "ssl"
                ),
            ),
            application_name=getter(
                "database_application_name",
                "telegram-bot",
            ),
        )

    def build_url(
        self,
    ) -> str:
        """
        Build an async SQLAlchemy URL.

        PostgreSQL is the production default.
        """

        if self.url:

            return normalize_database_url(
                self.url
            )

        return str(
            URL.create(
                drivername=(
                    "postgresql+asyncpg"
                ),
                username=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                database=self.name,
            )
        )

    def sanitized_url(
        self,
    ) -> str:

        url = self.build_url()

        try:

            parsed = URL.make_url(
                url
            )

            return str(
                parsed.render_as_string(
                    hide_password=True
                )
            )

        except Exception:

            return redact_database_url(
                url
            )


# ============================================================================
# Environment helpers
# ============================================================================

def _safe_int(
    value: Any,
    default: int,
) -> int:

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


def _safe_bool(
    value: Any,
    default: bool,
) -> bool:

    if isinstance(
        value,
        bool,
    ):

        return value

    if value is None:

        return default

    if isinstance(
        value,
        str,
    ):

        return value.lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }

    return bool(
        value
    )


def _int_env(
    name: str,
    default: int,
) -> int:

    return _safe_int(
        os.getenv(
            name
        ),
        default,
    )


def _bool_env(
    name: str,
    default: bool,
) -> bool:

    return _safe_bool(
        os.getenv(
            name
        ),
        default,
    )


# ============================================================================
# URL helpers
# ============================================================================

def normalize_database_url(
    url: str,
) -> str:

    value = str(
        url
    ).strip()

    if value.startswith(
        "postgres://"
    ):

        value = value.replace(
            "postgres://",
            "postgresql+asyncpg://",
            1,
        )

    elif value.startswith(
        "postgresql://"
    ):

        value = value.replace(
            "postgresql://",
            "postgresql+asyncpg://",
            1,
        )

    elif value.startswith(
        "postgresql+psycopg://"
    ):

        value = value.replace(
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            1,
        )

    elif value.startswith(
        "sqlite:///"
    ):

        value = value.replace(
            "sqlite:///",
            "sqlite+aiosqlite:///",
            1,
        )

    return value


def redact_database_url(
    url: str,
) -> str:

    value = str(
        url
    )

    try:

        parsed = URL.make_url(
            value
        )

        return str(
            parsed.render_as_string(
                hide_password=True
            )
        )

    except Exception:

        if "@" not in value:
            return value

        prefix, suffix = value.split(
            "@",
            1,
        )

        if ":" in prefix:

            prefix = prefix.rsplit(
                ":",
                1,
            )[0]

            prefix += ":***"

        return (
            prefix
            + "@"
            + suffix
        )


# ============================================================================
# Database manager
# ============================================================================

class DatabaseManager:
    """
    Owns the SQLAlchemy engine and async session factory.
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

        self.engine: Optional[
            AsyncEngine
        ] = None

        self.session_factory: Optional[
            async_sessionmaker[
                AsyncSession
            ]
        ] = None

        self.initialized = False

    # ------------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------------

    def create_engine(
        self,
    ) -> AsyncEngine:

        if self.engine is not None:

            return self.engine

        url = self.config.build_url()

        engine_kwargs: dict[
            str,
            Any,
        ] = {
            "echo": self.config.echo,
            "pool_pre_ping": True,
        }

        # SQLite does not support the PostgreSQL pool parameters.
        is_sqlite = url.startswith(
            "sqlite+"
        )

        if not is_sqlite:

            engine_kwargs.update(
                {
                    "pool_size": (
                        self.config.pool_size
                    ),
                    "max_overflow": (
                        self.config.max_overflow
                    ),
                    "pool_timeout": (
                        self.config.pool_timeout
                    ),
                    "pool_recycle": (
                        self.config.pool_recycle
                    ),
                }
            )

            connect_args: dict[
                str,
                Any,
            ] = {
                "timeout": (
                    self.config.connect_timeout
                ),
            }

            if self.config.ssl:

                connect_args[
                    "ssl"
                ] = self.config.ssl

            if self.config.application_name:

                connect_args[
                    "server_settings"
                ] = {
                    "application_name": (
                        self.config.application_name
                    )
                }

            engine_kwargs[
                "connect_args"
            ] = connect_args

        else:

            engine_kwargs[
                "connect_args"
            ] = {
                "timeout": (
                    self.config.connect_timeout
                )
            }

        self.engine = create_async_engine(
            url,
            **engine_kwargs,
        )

        self.session_factory = (
            async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
                autocommit=False,
            )
        )

        logger.info(
            "Database engine created: %s",
            self.config.sanitized_url(),
        )

        return self.engine

    # ------------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------------

    async def initialize(
        self,
    ) -> "DatabaseManager":

        if self.initialized:

            return self

        self.create_engine()

        await self.health_check(
            raise_on_error=True
        )

        self.initialized = True

        logger.info(
            "Database manager initialized."
        )

        return self

    # ------------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------------

    def session(
        self,
    ) -> AsyncSession:

        if self.session_factory is None:

            self.create_engine()

        if self.session_factory is None:

            raise RuntimeError(
                "Database session factory is unavailable."
            )

        return self.session_factory()

    @asynccontextmanager
    async def session_context(
        self,
    ) -> AsyncIterator[
        AsyncSession
    ]:

        session = self.session()

        try:

            yield session

        except Exception:

            await session.rollback()

            raise

        finally:

            await session.close()

    # ------------------------------------------------------------------------
    # Transaction
    # ------------------------------------------------------------------------

    @asynccontextmanager
    async def transaction(
        self,
    ) -> AsyncIterator[
        AsyncSession
    ]:

        session = self.session()

        try:

            async with session.begin():

                yield session

        except Exception:

            await session.rollback()

            raise

        finally:

            await session.close()

    # ------------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------------

    async def execute(
        self,
        statement,
        params: Optional[
            dict[str, Any]
        ] = None,
    ):

        async with self.session_context() as session:

            return await session.execute(
                statement,
                params or {},
            )

    async def scalar(
        self,
        statement,
        params: Optional[
            dict[str, Any]
        ] = None,
    ):

        result = await self.execute(
            statement,
            params,
        )

        return result.scalar()

    async def scalars(
        self,
        statement,
        params: Optional[
            dict[str, Any]
        ] = None,
    ):

        result = await self.execute(
            statement,
            params,
        )

        return result.scalars().all()

    # ------------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------------

    async def health_check(
        self,
        *,
        raise_on_error: bool = False,
    ) -> bool:

        if self.engine is None:

            self.create_engine()

        if self.engine is None:

            return False

        try:

            async with self.engine.connect() as connection:

                await connection.execute(
                    text(
                        "SELECT 1"
                    )
                )

            return True

        except Exception:

            logger.exception(
                "Database health check failed."
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

    # ------------------------------------------------------------------------
    # Commit / rollback helpers
    # ------------------------------------------------------------------------

    async def commit(
        self,
        session: AsyncSession,
    ) -> None:

        await session.commit()

    async def rollback(
        self,
        session: AsyncSession,
    ) -> None:

        await session.rollback()

    # ------------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------------

    async def close(
        self,
    ) -> None:

        if self.engine is None:

            self.initialized = False

            return

        try:

            await self.engine.dispose()

        finally:

            self.engine = None

            self.session_factory = None

            self.initialized = False

        logger.info(
            "Database engine disposed."
        )

    async def disconnect(
        self,
    ) -> None:

        await self.close()

    async def shutdown(
        self,
    ) -> None:

        await self.close()

    # ------------------------------------------------------------------------
    # Information
    # ------------------------------------------------------------------------

    def status(
        self,
    ) -> dict[str, Any]:

        return {
            "initialized": (
                self.initialized
            ),
            "engine_created": (
                self.engine is not None
            ),
            "session_factory_created": (
                self.session_factory is not None
            ),
            "database": (
                self.config.sanitized_url()
            ),
            "pool_size": (
                self.config.pool_size
            ),
            "max_overflow": (
                self.config.max_overflow
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

            _database_manager = existing

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

    existing = get_database_manager(
        app
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
# Session shortcuts
# ============================================================================

def get_session(
    app: Any = None,
) -> AsyncSession:

    manager = get_database_manager(
        app
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    return manager.session()


@asynccontextmanager
async def session(
    app: Any = None,
) -> AsyncIterator[
    AsyncSession
]:

    manager = get_database_manager(
        app
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    async with manager.session_context() as db_session:

        yield db_session


@asynccontextmanager
async def transaction(
    app: Any = None,
) -> AsyncIterator[
    AsyncSession
]:

    manager = get_database_manager(
        app
    )

    if manager is None:

        raise RuntimeError(
            "Database has not been initialized."
        )

    async with manager.transaction() as db_session:

        yield db_session


# ============================================================================
# Health shortcuts
# ============================================================================

async def health_check(
    app: Any = None,
) -> bool:

    manager = get_database_manager(
        app
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
# Close
# ============================================================================

async def close(
    app: Any = None,
) -> None:

    global _database_manager

    manager = get_database_manager(
        app
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
# SQLAlchemy compatibility helpers
# ============================================================================

def is_sqlalchemy_available() -> bool:

    return True


def get_engine(
    app: Any = None,
) -> Optional[
    AsyncEngine
]:

    manager = get_database_manager(
        app
    )

    if manager is None:
        return None

    if manager.engine is None:

        manager.create_engine()

    return manager.engine


def get_session_factory(
    app: Any = None,
):

    manager = get_database_manager(
        app
    )

    if manager is None:
        return None

    if manager.session_factory is None:

        manager.create_engine()

    return manager.session_factory


# ============================================================================
# Database error helper
# ============================================================================

def is_database_error(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        SQLAlchemyError,
    )


def database_error_message(
    exception: BaseException,
) -> str:

    if isinstance(
        exception,
        SQLAlchemyError,
    ):

        return (
            "Database operation failed."
        )

    return (
        "Unexpected database error."
    )


# ============================================================================
# Global status
# ============================================================================

async def status(
    app: Any = None,
) -> dict[str, Any]:

    manager = get_database_manager(
        app
    )

    if manager is None:

        return {
            "initialized": False,
            "healthy": False,
            "engine_created": False,
            "database": None,
        }

    healthy = await manager.health_check()

    result = manager.status()

    result[
        "healthy"
    ] = healthy

    return result


# ============================================================================
# Reset helper
# ============================================================================

async def reset_manager() -> None:

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

    "normalize_database_url",
    "redact_database_url",

    "get_database_manager",
    "set_database_manager",

    "initialize",
    "init_database",

    "get_session",
    "session",
    "transaction",

    "health_check",
    "ping",

    "close",
    "disconnect",

    "get_engine",
    "get_session_factory",

    "is_sqlalchemy_available",
    "is_database_error",
    "database_error_message",

    "status",
    "reset_manager",
]