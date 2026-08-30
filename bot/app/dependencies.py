
"""
bot.app.dependencies

Central dependency construction for the application.

This module is responsible for creating infrastructure objects and
constructing the application's service and middleware dependencies.

Important:
    - Database connections are owned by DatabaseManager.
    - Redis is optional.
    - Cache is optional.
    - Services are constructed here, but business logic stays in services.
    - Missing optional integrations are logged instead of crashing imports.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any

from bot.core.config import Settings

from .container import ApplicationContainer


logger = logging.getLogger("bot.app.dependencies")


# ============================================================================
# Generic helpers
# ============================================================================


def _safe_get(
    obj: Any,
    name: str,
    default: Any = None,
) -> Any:
    """
    Safely read an attribute from an object.

    Supports normal objects and dictionaries.
    """

    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(
        obj,
        name,
        default,
    )


def _construct(
    factory: Any,
    **kwargs: Any,
) -> Any:
    """
    Construct an object while passing only arguments accepted by its
    constructor.

    This prevents the dependency layer from breaking when an existing
    service has a smaller constructor than the common service contract.

    If the constructor accepts **kwargs, all supplied values are passed.
    """

    try:
        signature = inspect.signature(factory)

    except (TypeError, ValueError):
        return factory(**kwargs)

    parameters = signature.parameters

    accepts_kwargs = any(
        parameter.kind
        == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )

    if accepts_kwargs:
        return factory(**kwargs)

    accepted = {
        name: value
        for name, value in kwargs.items()
        if name in parameters
    }

    return factory(**accepted)


def _log_optional_failure(
    component: str,
    exc: Exception,
) -> None:
    logger.warning(
        "Unable to construct optional component %s: %s",
        component,
        exc,
    )


# ============================================================================
# Database
# ============================================================================


def create_database(
    settings: Settings,
) -> Any:
    """
    Create the project's existing DatabaseManager.

    The actual connection is not opened here. DatabaseManager creates
    its engine lazily and initialize() performs the connection health
    check.
    """

    from bot.database.connection import (
        DatabaseConfig,
        DatabaseManager,
    )

    database_settings = _safe_get(
        settings,
        "database",
        None,
    )

    database_config = DatabaseConfig.from_config(
        database_settings
    )

    manager = DatabaseManager(
        database_config
    )

    logger.info(
        "Database manager created: %s",
        database_config.sanitized_url(),
    )

    return manager


# ============================================================================
# Redis
# ============================================================================


def create_redis(
    settings: Settings,
) -> Any:
    """
    Create the existing Redis implementation when enabled.

    Redis is intentionally optional so development environments can
    disable it without preventing the application from importing.
    """

    redis_settings = _safe_get(
        settings,
        "redis",
        None,
    )

    enabled = _safe_get(
        redis_settings,
        "enabled",
        True,
    )

    if not enabled:
        logger.info(
            "Redis is disabled by configuration."
        )

        return None

    try:
        from bot.database.redis import (
            RedisClient,
        )

    except ImportError:
        logger.warning(
            "RedisClient is unavailable; continuing without Redis."
        )

        return None

    try:
        return _construct(
            RedisClient,
            settings=redis_settings,
            config=redis_settings,
            redis=redis_settings,
        )

    except Exception as exc:
        _log_optional_failure(
            "redis",
            exc,
        )

        return None


# ============================================================================
# Cache
# ============================================================================


def create_cache(
    settings: Settings,
    redis: Any = None,
) -> Any:
    """
    Create the project's cache implementation.

    Cache remains optional. A missing cache must not prevent the bot
    from starting unless a particular service explicitly requires it.
    """

    try:
        from bot.database.cache import (
            Cache,
        )

    except ImportError:
        logger.info(
            "Cache implementation is unavailable; "
            "continuing without cache."
        )

        return None

    try:
        return _construct(
            Cache,
            settings=settings,
            redis=redis,
        )

    except Exception as exc:
        _log_optional_failure(
            "cache",
            exc,
        )

        return None


# ============================================================================
# Individual service helpers
# ============================================================================


def _create_search_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.search import (
        SearchService,
    )

    return _construct(
        SearchService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_movie_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.movie import (
        MovieService,
    )

    return _construct(
        MovieService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_delivery_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.delivery import (
        DeliveryService,
    )

    return _construct(
        DeliveryService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_verification_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.verification import (
        VerificationService,
    )

    return _construct(
        VerificationService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_shortener_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.shortener import (
        ShortenerService,
    )

    return _construct(
        ShortenerService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_file_search_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.file_search import (
        FileSearchService,
    )

    return _construct(
        FileSearchService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_filter_service(
    container: ApplicationContainer,
) -> Any:

    # IMPORTANT:
    # The actual project file is filters.py, not filter.py.
    from bot.services.filters import (
        FilterService,
    )

    return _construct(
        FilterService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_broadcast_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.broadcast import (
        BroadcastService,
    )

    return _construct(
        BroadcastService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_moderation_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.moderation import (
        ModerationService,
    )

    return _construct(
        ModerationService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


def _create_indexer_service(
    container: ApplicationContainer,
) -> Any:

    from bot.services.indexer import (
        IndexerService,
    )

    return _construct(
        IndexerService,
        database=container.database,
        cache=container.cache,
        redis=container.redis,
        settings=container.settings,
    )


# ============================================================================
# Service factory
# ============================================================================


SERVICE_FACTORIES = {
    "search": _create_search_service,
    "movie": _create_movie_service,
    "delivery": _create_delivery_service,
    "verification": _create_verification_service,
    "shortener": _create_shortener_service,
    "file_search": _create_file_search_service,
    "filter": _create_filter_service,
    "broadcast": _create_broadcast_service,
    "moderation": _create_moderation_service,
    "indexer": _create_indexer_service,
}


def create_services(
    container: ApplicationContainer,
) -> dict[str, Any]:
    """
    Construct all application services.

    Each service is isolated so one optional service import failure
    does not prevent unrelated services from loading.
    """

    services: dict[
        str,
        Any,
    ] = {}

    for name, factory in SERVICE_FACTORIES.items():

        try:
            service = factory(
                container
            )

        except ImportError as exc:
            logger.warning(
                "Service '%s' could not be imported: %s",
                name,
                exc,
            )

            continue

        except Exception:
            logger.exception(
                "Service '%s' failed during construction.",
                name,
            )

            continue

        if service is None:
            continue

        services[name] = service

        logger.debug(
            "Service registered: %s",
            name,
        )

    return services


# ============================================================================
# Middleware
# ============================================================================


def create_middleware(
    container: ApplicationContainer,
) -> dict[str, Any]:
    """
    Construct middleware.

    Middleware imports are performed individually so that an optional
    middleware component does not prevent the application from loading.
    """

    middleware: dict[
        str,
        Any,
    ] = {}

    # ------------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------------

    try:
        from bot.middleware.auth import (
            AuthMiddleware,
        )

        middleware["auth"] = _construct(
            AuthMiddleware,
            database=container.database,
            redis=container.redis,
            cache=container.cache,
            settings=container.settings,
        )

    except ImportError as exc:
        logger.warning(
            "Authentication middleware unavailable: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Authentication middleware failed to initialize."
        )

    # ------------------------------------------------------------------------
    # Administration
    # ------------------------------------------------------------------------

    try:
        from bot.middleware.admin import (
            AdminMiddleware,
        )

        app_settings = _safe_get(
            container.settings,
            "app",
            None,
        )

        admin_ids = _safe_get(
            app_settings,
            "admin_ids",
            [],
        )

        middleware["admin"] = _construct(
            AdminMiddleware,
            admin_ids=admin_ids,
            database=container.database,
            admin_repository=container.database,
            settings=container.settings,
        )

    except ImportError as exc:
        logger.warning(
            "Admin middleware unavailable: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Admin middleware failed to initialize."
        )

    # ------------------------------------------------------------------------
    # Throttling
    # ------------------------------------------------------------------------

    try:
        from bot.middleware.throttling import (
            ThrottlingMiddleware,
        )

        middleware["throttling"] = _construct(
            ThrottlingMiddleware,
            database=container.database,
            redis=container.redis,
            cache=container.cache,
            settings=container.settings,
        )

    except ImportError as exc:
        logger.warning(
            "Throttling middleware unavailable: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Throttling middleware failed to initialize."
        )

    # ------------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------------

    try:
        from bot.middleware.logging import (
            LoggingMiddleware,
        )

        middleware["logging"] = _construct(
            LoggingMiddleware,
            settings=container.settings,
        )

    except ImportError as exc:
        logger.warning(
            "Logging middleware unavailable: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Logging middleware failed to initialize."
        )

    return middleware


# ============================================================================
# Container construction
# ============================================================================


def build_container(
    settings: Settings,
    *,
    database: Any = None,
    redis: Any = None,
    cache: Any = None,
) -> ApplicationContainer:
    """
    Build the complete application dependency container.

    Explicitly supplied dependencies always take precedence over the
    default factories. This makes the container easy to test.
    """

    if settings is None:
        raise ValueError(
            "settings is required."
        )

    if database is None:
        database = create_database(
            settings
        )

    if redis is None:
        redis = create_redis(
            settings
        )

    if cache is None:
        cache = create_cache(
            settings,
            redis,
        )

    container = ApplicationContainer(
        settings,
        database=database,
        redis=redis,
        cache=cache,
    )

    # ------------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------------

    services = create_services(
        container
    )

    for name, service in services.items():

        container.register_service(
            name,
            service,
        )

    # ------------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------------

    middleware = create_middleware(
        container
    )

    for name, item in middleware.items():

        container.register_middleware(
            name,
            item,
        )

    logger.info(
        "Dependency container built: "
        "%d services, %d middleware components.",
        len(services),
        len(middleware),
    )

    return container


# ============================================================================
# Validation
# ============================================================================


def validate_container(
    container: ApplicationContainer,
) -> list[str]:
    """
    Perform lightweight dependency validation.

    This function intentionally does not establish external connections.
    """

    errors: list[str] = []

    if container is None:
        return [
            "Application container is None."
        ]

    if container.settings is None:
        errors.append(
            "Settings dependency is missing."
        )

    if container.database is None:
        errors.append(
            "Database dependency is missing."
        )

    return errors


# ============================================================================
# Diagnostics
# ============================================================================


def dependency_summary(
    container: ApplicationContainer,
) -> dict[str, Any]:
    """
    Return a safe diagnostic summary.

    Secrets and credentials are never included.
    """

    services = {}

    try:
        services = {
            name: type(service).__name__
            for name, service
            in container.services.items()
        }

    except Exception:
        services = {}

    middleware = {}

    try:
        middleware = {
            name: type(item).__name__
            for name, item
            in container.middleware.items()
        }

    except Exception:
        middleware = {}

    return {
        "database": (
            type(container.database).__name__
            if container.database is not None
            else None
        ),
        "redis": (
            type(container.redis).__name__
            if container.redis is not None
            else None
        ),
        "cache": (
            type(container.cache).__name__
            if container.cache is not None
            else None
        ),
        "services": services,
        "middleware": middleware,
    }


# ============================================================================
# Exports
# ============================================================================


__all__ = [
    "SERVICE_FACTORIES",
    "create_database",
    "create_redis",
    "create_cache",
    "create_services",
    "create_middleware",
    "build_container",
    "validate_container",
    "dependency_summary",
]

