"""
bot.app.container

Dependency container for the Telegram bot.

The container owns application-wide dependencies and provides a
single composition root.

Responsibilities:
    - Store Settings.
    - Store database infrastructure.
    - Store Redis/cache infrastructure.
    - Store services.
    - Store middleware.
    - Store handler registry.
    - Control initialization and shutdown.
    - Prevent accidental duplicate construction.

The container deliberately does not contain business logic.
Business logic belongs in services.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bot.core.config import Settings, get_settings
from bot.core.lifecycle import LifecycleManager


logger = logging.getLogger(
    "bot.app.container"
)


# ============================================================================
# Container state
# ============================================================================

@dataclass(slots=True)
class ContainerState:
    """
    Runtime state for the dependency container.
    """

    initialized: bool = False

    starting: bool = False

    stopping: bool = False

    stopped: bool = False

    services_ready: bool = False

    middleware_ready: bool = False

    handlers_ready: bool = False


# ============================================================================
# Application container
# ============================================================================

class ApplicationContainer:
    """
    Central dependency container.

    The container is intentionally explicit. Dependencies can be injected
    from outside for tests and alternative deployments.

    Example:

        container = ApplicationContainer(settings)

        await container.initialize()

        search = container.get_service("search")
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        database: Any = None,
        redis: Any = None,
        cache: Any = None,
        services: Optional[
            dict[str, Any]
        ] = None,
        middleware: Optional[
            dict[str, Any]
        ] = None,
        handlers: Optional[
            dict[str, Any]
        ] = None,
    ) -> None:

        self.settings = (
            settings
            or get_settings()
        )

        self.database = database

        self.redis = redis

        self.cache = cache

        self.services: dict[
            str,
            Any,
        ] = dict(
            services
            or {}
        )

        self.middleware: dict[
            str,
            Any,
        ] = dict(
            middleware
            or {}
        )

        self.handlers: dict[
            str,
            Any,
        ] = dict(
            handlers
            or {}
        )

        self.state = ContainerState()

        self.lifecycle = LifecycleManager(
            self.settings,
            database=self.database,
            redis=self.redis,
        )

        self._lock = asyncio.Lock()

    # ========================================================================
    # Registration
    # ========================================================================

    def register_service(
        self,
        name: str,
        service: Any,
        *,
        replace: bool = False,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        if (
            key in self.services
            and not replace
        ):

            raise ValueError(
                f"Service '{key}' is already registered."
            )

        self.services[key] = service

        return service

    def register_middleware(
        self,
        name: str,
        middleware: Any,
        *,
        replace: bool = False,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        if (
            key in self.middleware
            and not replace
        ):

            raise ValueError(
                f"Middleware '{key}' is already registered."
            )

        self.middleware[key] = middleware

        return middleware

    def register_handler(
        self,
        name: str,
        handler: Any,
        *,
        replace: bool = False,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        if (
            key in self.handlers
            and not replace
        ):

            raise ValueError(
                f"Handler '{key}' is already registered."
            )

        self.handlers[key] = handler

        return handler

    # ========================================================================
    # Retrieval
    # ========================================================================

    def get_service(
        self,
        name: str,
        *,
        required: bool = True,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        value = self.services.get(
            key
        )

        if (
            value is None
            and required
        ):

            raise KeyError(
                f"Service '{key}' is not registered."
            )

        return value

    def get_middleware(
        self,
        name: str,
        *,
        required: bool = True,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        value = self.middleware.get(
            key
        )

        if (
            value is None
            and required
        ):

            raise KeyError(
                f"Middleware '{key}' is not registered."
            )

        return value

    def get_handler(
        self,
        name: str,
        *,
        required: bool = True,
    ) -> Any:

        key = self._normalize_name(
            name
        )

        value = self.handlers.get(
            key
        )

        if (
            value is None
            and required
        ):

            raise KeyError(
                f"Handler '{key}' is not registered."
            )

        return value

    # ========================================================================
    # Normalization
    # ========================================================================

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:

        if not isinstance(
            name,
            str,
        ):

            raise TypeError(
                "Dependency name must be a string."
            )

        value = name.strip().lower()

        if not value:
            raise ValueError(
                "Dependency name cannot be empty."
            )

        return value

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(
        self,
    ) -> None:

        async with self._lock:

            if self.state.initialized:
                return

            if self.state.starting:
                raise RuntimeError(
                    "Container is already starting."
                )

            self.state.starting = True
            self.state.stopped = False

            logger.info(
                "Initializing application container."
            )

            try:

                self.settings.validate()

                await self.lifecycle.initialize_database()

                await self.lifecycle.initialize_redis()

                await self._initialize_services()

                await self._initialize_middleware()

                await self._initialize_handlers()

                self.state.initialized = True

                self.state.starting = False

                logger.info(
                    "Application container initialized."
                )

            except Exception:

                self.state.starting = False

                logger.exception(
                    "Application container initialization failed."
                )

                await self._shutdown_components()

                raise

    async def _initialize_services(
        self,
    ) -> None:

        for name, service in self.services.items():

            await self._initialize_object(
                service,
                f"service:{name}",
            )

        self.state.services_ready = True

    async def _initialize_middleware(
        self,
    ) -> None:

        for name, middleware in self.middleware.items():

            await self._initialize_object(
                middleware,
                f"middleware:{name}",
            )

        self.state.middleware_ready = True

    async def _initialize_handlers(
        self,
    ) -> None:

        for name, handler in self.handlers.items():

            await self._initialize_object(
                handler,
                f"handler:{name}",
            )

        self.state.handlers_ready = True

    @staticmethod
    async def _initialize_object(
        obj: Any,
        name: str,
    ) -> None:

        if obj is None:
            return

        for method_name in (
            "initialize",
            "init",
            "start",
        ):

            method = getattr(
                obj,
                method_name,
                None,
            )

            if method is None:
                continue

            result = method()

            if hasattr(
                result,
                "__await__",
            ):

                await result

            logger.debug(
                "Initialized %s.",
                name,
            )

            return

    # ========================================================================
    # Shutdown
    # ========================================================================

    async def shutdown(
        self,
    ) -> None:

        async with self._lock:

            if self.state.stopped:
                return

            self.state.stopping = True

            logger.info(
                "Shutting down application container."
            )

            try:

                await self._shutdown_components()

            finally:

                self.state.initialized = False

                self.state.starting = False

                self.state.stopping = False

                self.state.stopped = True

    async def _shutdown_components(
        self,
    ) -> None:

        await self._shutdown_mapping(
            self.handlers,
            "handler",
        )

        await self._shutdown_mapping(
            self.middleware,
            "middleware",
        )

        await self._shutdown_mapping(
            self.services,
            "service",
        )

        await self.lifecycle.shutdown_redis()

        await self.lifecycle.shutdown_database()

        self.state.handlers_ready = False

        self.state.middleware_ready = False

        self.state.services_ready = False

    @staticmethod
    async def _shutdown_mapping(
        mapping: dict[str, Any],
        category: str,
    ) -> None:

        for name, obj in reversed(
            list(mapping.items())
        ):

            if obj is None:
                continue

            for method_name in (
                "shutdown",
                "close",
                "stop",
            ):

                method = getattr(
                    obj,
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

                except Exception:

                    logger.exception(
                        "Failed to shut down %s:%s.",
                        category,
                        name,
                    )

                break

    # ========================================================================
    # State
    # ========================================================================

    @property
    def ready(
        self,
    ) -> bool:

        return (
            self.state.initialized
            and not self.state.stopping
        )

    def summary(
        self,
    ) -> dict[str, Any]:

        return {
            "initialized": self.state.initialized,
            "starting": self.state.starting,
            "stopping": self.state.stopping,
            "stopped": self.state.stopped,
            "services": list(
                self.services.keys()
            ),
            "middleware": list(
                self.middleware.keys()
            ),
            "handlers": list(
                self.handlers.keys()
            ),
            "database": self.database is not None,
            "redis": self.redis is not None,
            "cache": self.cache is not None,
        }

    # ========================================================================
    # Context manager
    # ========================================================================

    async def __aenter__(
        self,
    ) -> "ApplicationContainer":

        await self.initialize()

        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        await self.shutdown()


__all__ = [
    "ContainerState",
    "ApplicationContainer",
]