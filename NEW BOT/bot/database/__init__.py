"""
bot.database

Database package for the bot.

Architecture
------------
The database layer is split into:

    connection.py   -> database engine/session lifecycle
    models.py       -> shared database models/schema
    users.py        -> user accounts
    groups.py       -> Telegram groups
    files.py        -> stored Telegram files
    requests.py     -> file/search/request tracking
    premium.py      -> premium subscriptions
    verification.py -> verification state
    settings.py     -> user/group/bot settings

Handlers and services should use this package rather than talking
directly to the database engine.

Example:

    from bot.database import users

    user = await users.get_user(
        user_id
    )

The package also exposes a DatabaseManager when connection.py
provides one.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Package metadata
# ============================================================================

__version__ = "1.0.0"

__title__ = "Bot Database Layer"


# ============================================================================
# Lazy module imports
# ============================================================================

_MODULES = (
    "connection",
    "models",
    "users",
    "groups",
    "files",
    "requests",
    "premium",
    "verification",
    "settings",
)


def load_module(
    name: str,
) -> Optional[Any]:
    """
    Lazily load one database submodule.

    This avoids importing every database component during application
    startup and also helps prevent circular imports.
    """

    import importlib

    normalized = (
        str(name)
        .strip()
        .lower()
    )

    if normalized not in _MODULES:

        raise ValueError(
            f"Unknown database module: {name}"
        )

    try:

        return importlib.import_module(
            f"bot.database.{normalized}"
        )

    except ImportError:

        logger.exception(
            "Unable to load database module: %s",
            normalized,
        )

        return None


# ============================================================================
# Database module accessors
# ============================================================================

def get_connection_module():

    return load_module(
        "connection"
    )


def get_models_module():

    return load_module(
        "models"
    )


def get_users_module():

    return load_module(
        "users"
    )


def get_groups_module():

    return load_module(
        "groups"
    )


def get_files_module():

    return load_module(
        "files"
    )


def get_requests_module():

    return load_module(
        "requests"
    )


def get_premium_module():

    return load_module(
        "premium"
    )


def get_verification_module():

    return load_module(
        "verification"
    )


def get_settings_module():

    return load_module(
        "settings"
    )


# ============================================================================
# Database manager access
# ============================================================================

def get_database_manager(
    app: Any = None,
) -> Optional[Any]:
    """
    Retrieve the application's DatabaseManager.

    Priority:

        1. app.db
        2. app.database
        3. connection.get_database_manager()
    """

    if app is not None:

        database = getattr(
            app,
            "db",
            None,
        )

        if database is not None:

            return database

        database = getattr(
            app,
            "database",
            None,
        )

        if database is not None:

            return database

    try:

        connection = get_connection_module()

        if connection is None:
            return None

        getter = getattr(
            connection,
            "get_database_manager",
            None,
        )

        if getter is None:
            return None

        if app is not None:

            try:

                return getter(
                    app
                )

            except TypeError:

                return getter()

        return getter()

    except Exception:

        logger.exception(
            "Unable to retrieve database manager."
        )

        return None


# ============================================================================
# Database initialization
# ============================================================================

async def initialize(
    app: Any = None,
    *,
    config: Any = None,
) -> Any:
    """
    Initialize the database layer.

    The actual connection implementation lives in connection.py.
    """

    connection = get_connection_module()

    if connection is None:

        raise RuntimeError(
            "Database connection module is unavailable."
        )

    initializer = getattr(
        connection,
        "initialize",
        None,
    )

    if initializer is None:

        initializer = getattr(
            connection,
            "init_database",
            None,
        )

    if initializer is None:

        raise RuntimeError(
            "Database connection module does not provide "
            "initialize() or init_database()."
        )

    try:

        result = initializer(
            app=app,
            config=config,
        )

    except TypeError:

        try:

            result = initializer(
                app
            )

        except TypeError:

            result = initializer()

    if hasattr(
        result,
        "__await__",
    ):

        result = await result

    if app is not None and result is not None:

        try:

            setattr(
                app,
                "db",
                result,
            )

        except Exception:

            logger.debug(
                "Unable to attach database manager to app.",
                exc_info=True,
            )

    logger.info(
        "Database layer initialized."
    )

    return result


# ============================================================================
# Database shutdown
# ============================================================================

async def close(
    app: Any = None,
) -> None:
    """
    Close the database connection cleanly.
    """

    database = get_database_manager(
        app
    )

    if database is None:
        return

    for method_name in (
        "close",
        "disconnect",
        "shutdown",
    ):

        method = getattr(
            database,
            method_name,
            None,
        )

        if method is None:
            continue

        try:

            result = method()

            if hasattr(
                result,
                "__await__",
            ):

                await result

            logger.info(
                "Database connection closed."
            )

            return

        except Exception:

            logger.exception(
                "Database shutdown failed."
            )

            return


# ============================================================================
# Health check
# ============================================================================

async def health_check(
    app: Any = None,
) -> bool:
    """
    Check whether the database is reachable.
    """

    database = get_database_manager(
        app
    )

    if database is None:

        return False

    for method_name in (
        "health_check",
        "ping",
        "check_connection",
        "is_healthy",
    ):

        method = getattr(
            database,
            method_name,
            None,
        )

        if method is None:
            continue

        try:

            result = method()

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return bool(
                result
            )

        except Exception:

            logger.exception(
                "Database health check failed."
            )

            return False

    # If the manager has no explicit health method, assume it is
    # initialized and available.
    return True


# ============================================================================
# Transaction helper
# ============================================================================

async def transaction(
    app: Any = None,
):
    """
    Return the database transaction/context manager.

    Usage:

        async with database.transaction(app):
            ...

    The actual implementation is supplied by connection.py.
    """

    database = get_database_manager(
        app
    )

    if database is None:

        raise RuntimeError(
            "Database manager is not initialized."
        )

    transaction_method = getattr(
        database,
        "transaction",
        None,
    )

    if transaction_method is None:

        raise RuntimeError(
            "Database manager does not provide transaction()."
        )

    return transaction_method()


# ============================================================================
# Generic repository access
# ============================================================================

def repository(
    name: str,
    app: Any = None,
) -> Any:
    """
    Retrieve a repository from the application database manager.

    Example:

        users_repo = repository("users", app)
    """

    database = get_database_manager(
        app
    )

    if database is None:

        raise RuntimeError(
            "Database manager is not initialized."
        )

    normalized = (
        str(name)
        .strip()
        .lower()
    )

    # Direct attribute.
    value = getattr(
        database,
        normalized,
        None,
    )

    if value is not None:

        return value

    # Common repository naming conventions.
    for attribute in (
        f"{normalized}_repository",
        f"{normalized}_repo",
    ):

        value = getattr(
            database,
            attribute,
            None,
        )

        if value is not None:

            return value

    # Generic getter.
    getter = getattr(
        database,
        "get_repository",
        None,
    )

    if getter is not None:

        result = getter(
            normalized
        )

        return result

    raise AttributeError(
        f"Database repository not found: {name}"
    )


# ============================================================================
# Database status
# ============================================================================

async def status(
    app: Any = None,
) -> dict[str, Any]:
    """
    Return a safe database status report.
    """

    database = get_database_manager(
        app
    )

    if database is None:

        return {
            "initialized": False,
            "healthy": False,
            "backend": None,
        }

    backend = (
        type(
            database
        ).__name__
    )

    healthy = await health_check(
        app
    )

    return {
        "initialized": True,
        "healthy": healthy,
        "backend": backend,
    }


# ============================================================================
# Safe operation helper
# ============================================================================

async def safe_call(
    function,
    *args,
    default: Any = None,
    **kwargs,
) -> Any:
    """
    Execute a database operation without allowing an expected database
    failure to crash an entire Telegram update.

    Critical transactions should NOT use this helper when failure must
    propagate to the caller.
    """

    try:

        result = function(
            *args,
            **kwargs,
        )

        if hasattr(
            result,
            "__await__",
        ):

            result = await result

        return result

    except Exception:

        logger.exception(
            "Database operation failed: %s",
            getattr(
                function,
                "__name__",
                repr(function),
            ),
        )

        return default


# ============================================================================
# Module discovery
# ============================================================================

def available_modules() -> list[str]:

    return list(
        _MODULES
    )


def module_available(
    name: str,
) -> bool:

    try:

        module = load_module(
            name
        )

        return module is not None

    except (
        ValueError,
    ):

        return False


# ============================================================================
# Startup validation
# ============================================================================

def validate_structure() -> dict[
    str,
    bool,
]:
    """
    Validate that all expected database modules can be imported.

    This does not connect to the database.
    """

    result: dict[
        str,
        bool,
    ] = {}

    for module_name in _MODULES:

        try:

            module = load_module(
                module_name
            )

            result[
                module_name
            ] = module is not None

        except Exception:

            result[
                module_name
            ] = False

    return result


def structure_report() -> str:

    result = validate_structure()

    lines = [
        "Database package",
        "=" * 32,
    ]

    for name in _MODULES:

        status = (
            "OK"
            if result.get(
                name,
                False,
            )
            else "MISSING"
        )

        lines.append(
            f"{name:<16} {status}"
        )

    return "\n".join(
        lines
    )


# ============================================================================
# Public exports
# ============================================================================

__all__ = [
    "__version__",
    "__title__",

    "load_module",

    "get_connection_module",
    "get_models_module",
    "get_users_module",
    "get_groups_module",
    "get_files_module",
    "get_requests_module",
    "get_premium_module",
    "get_verification_module",
    "get_settings_module",

    "get_database_manager",

    "initialize",
    "close",
    "health_check",

    "transaction",
    "repository",

    "status",
    "safe_call",

    "available_modules",
    "module_available",

    "validate_structure",
    "structure_report",
]