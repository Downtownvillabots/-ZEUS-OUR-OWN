"""
bot.integration.wiring

Main application composition layer.

This module connects the existing application layers:

    core
      ↓
    database
      ↓
    services
      ↓
    middleware
      ↓
    handlers
      ↓
    Telegram Application

The wiring layer is deliberately kept separate from business logic.

It is responsible for:
    - constructing registries
    - discovering existing components
    - registering services
    - registering middleware
    - registering handlers
    - installing components into the Telegram application
    - validating the resulting graph
    - initializing components
    - shutting components down

The exact implementations of services, handlers, and middleware can vary.
The adapters below therefore support the common registration patterns used
by the existing bot modules.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from bot.core.config import Settings

from .checks import StartupChecker
from .handler_registry import HandlerRegistry
from .health import HealthChecker
from .middleware_registry import MiddlewareRegistry
from .service_registry import ServiceRegistry


logger = logging.getLogger(
    "bot.integration.wiring"
)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_SERVICE_MODULES = (
    "bot.services.search",
    "bot.services.movie",
    "bot.services.delivery",
    "bot.services.shortener",
    "bot.services.verification",
    "bot.services.file_search",
    "bot.services.filter",
    "bot.services.broadcast",
    "bot.services.moderation",
    "bot.services.indexer",
)

DEFAULT_MIDDLEWARE_MODULES = (
    "bot.middleware.auth",
    "bot.middleware.admin",
    "bot.middleware.throttling",
    "bot.middleware.logging",
    "bot.middleware.errors",
)

DEFAULT_HANDLER_MODULES = (
    "bot.handlers.start",
    "bot.handlers.search",
    "bot.handlers.user",
    "bot.handlers.admin",
    "bot.handlers.init",
)


# ============================================================================
# Wiring state
# ============================================================================

@dataclass(slots=True)
class WiringState:
    """
    Runtime state for application composition.
    """

    services_registered: bool = False

    middleware_registered: bool = False

    handlers_registered: bool = False

    application_installed: bool = False

    initialized: bool = False

    shutdown: bool = False

    validated: bool = False


# ============================================================================
# Wiring result
# ============================================================================

@dataclass(slots=True)
class WiringResult:
    """
    Result returned from the composition process.
    """

    success: bool

    services: int = 0

    middleware: int = 0

    handlers: int = 0

    errors: list[str] = field(
        default_factory=list
    )

    warnings: list[str] = field(
        default_factory=list
    )

    details: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# Component specification
# ============================================================================

@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """
    Describes a component that should be discovered or constructed.
    """

    name: str

    module: str

    class_names: tuple[str, ...] = ()

    factory_names: tuple[str, ...] = ()

    priority: int = 100

    required: bool = False

    enabled: bool = True


# ============================================================================
# Application wiring
# ============================================================================

class ApplicationWiring:
    """
    Coordinates the complete application composition.

    Example:

        wiring = build_wiring(
            settings,
            container=container,
        )

        await wiring.initialize()

        wiring.install_into_telegram(application)

        checks = await wiring.check()
    """

    def __init__(
        self,
        settings: Settings,
        *,
        container: Any = None,
        database: Any = None,
        redis: Any = None,
        cache: Any = None,
        service_registry: Optional[
            ServiceRegistry
        ] = None,
        handler_registry: Optional[
            HandlerRegistry
        ] = None,
        middleware_registry: Optional[
            MiddlewareRegistry
        ] = None,
    ) -> None:

        self.settings = settings

        self.container = container

        self.database = database

        self.redis = redis

        self.cache = cache

        self.services = (
            service_registry
            or ServiceRegistry()
        )

        self.handlers = (
            handler_registry
            or HandlerRegistry()
        )

        self.middleware = (
            middleware_registry
            or MiddlewareRegistry()
        )

        self.state = WiringState()

        self._telegram_application: Any = None

        self._loaded_modules: dict[
            str,
            Any,
        ] = {}

    # ========================================================================
    # Public composition
    # ========================================================================

    def compose(
        self,
        *,
        discover: bool = True,
    ) -> WiringResult:

        errors: list[str] = []

        warnings: list[str] = []

        if discover:

            try:

                self.discover_services()

            except Exception as exc:

                errors.append(
                    f"Service discovery failed: {exc}"
                )

            try:

                self.discover_middleware()

            except Exception as exc:

                errors.append(
                    f"Middleware discovery failed: {exc}"
                )

            try:

                self.discover_handlers()

            except Exception as exc:

                errors.append(
                    f"Handler discovery failed: {exc}"
                )

        try:

            errors.extend(
                self.validate()
            )

        except Exception as exc:

            errors.append(
                f"Composition validation failed: {exc}"
            )

        self.state.validated = (
            not errors
        )

        result = WiringResult(
            success=not errors,
            services=len(
                self.services
            ),
            middleware=len(
                self.middleware
            ),
            handlers=len(
                self.handlers
            ),
            errors=errors,
            warnings=warnings,
            details=self.summary(),
        )

        return result

    # ========================================================================
    # Service discovery
    # ========================================================================

    def discover_services(
        self,
        specs: Optional[
            Iterable[ComponentSpec]
        ] = None,
    ) -> int:

        specifications = tuple(
            specs
            or self._default_service_specs()
        )

        count = 0

        for spec in specifications:

            if not spec.enabled:
                continue

            module = self._import_module(
                spec.module
            )

            if module is None:
                continue

            instance = self._resolve_component(
                module,
                spec,
            )

            if instance is None:
                continue

            if self.services.contains(
                spec.name
            ):

                continue

            self.services.register(
                spec.name,
                instance,
                enabled=spec.enabled,
                required=spec.required,
                priority=spec.priority,
            )

            count += 1

        self.state.services_registered = True

        return count

    # ========================================================================
    # Middleware discovery
    # ========================================================================

    def discover_middleware(
        self,
        specs: Optional[
            Iterable[ComponentSpec]
        ] = None,
    ) -> int:

        specifications = tuple(
            specs
            or self._default_middleware_specs()
        )

        count = 0

        for spec in specifications:

            if not spec.enabled:
                continue

            module = self._import_module(
                spec.module
            )

            if module is None:
                continue

            instance = self._resolve_component(
                module,
                spec,
            )

            if instance is None:
                continue

            if self.middleware_name_exists(
                spec.name
            ):

                continue

            self.middleware.register(
                spec.name,
                instance,
                priority=spec.priority,
                enabled=spec.enabled,
            )

            count += 1

        self.state.middleware_registered = True

        return count

    # ========================================================================
    # Handler discovery
    # ========================================================================

    def discover_handlers(
        self,
        specs: Optional[
            Iterable[ComponentSpec]
        ] = None,
    ) -> int:

        specifications = tuple(
            specs
            or self._default_handler_specs()
        )

        count = 0

        for spec in specifications:

            if not spec.enabled:
                continue

            module = self._import_module(
                spec.module
            )

            if module is None:
                continue

            components = (
                self._resolve_handlers(
                    module,
                    spec,
                )
            )

            for index, component in enumerate(
                components
            ):

                name = spec.name

                if len(components) > 1:

                    name = (
                        f"{spec.name}_{index + 1}"
                    )

                if self.handler_name_exists(
                    name
                ):

                    continue

                self.handlers.register(
                    name,
                    component,
                    group=spec.priority,
                    priority=index,
                    enabled=spec.enabled,
                )

                count += 1

        self.state.handlers_registered = True

        return count

    # ========================================================================
    # Default specifications
    # ========================================================================

    def _default_service_specs(
        self,
    ) -> tuple[ComponentSpec, ...]:

        return (
            ComponentSpec(
                name="search",
                module="bot.services.search",
                class_names=(
                    "SearchService",
                    "Search",
                ),
                factory_names=(
                    "create_search_service",
                    "create_service",
                ),
                priority=10,
            ),
            ComponentSpec(
                name="movie",
                module="bot.services.movie",
                class_names=(
                    "MovieService",
                    "Movie",
                ),
                factory_names=(
                    "create_movie_service",
                    "create_service",
                ),
                priority=20,
            ),
            ComponentSpec(
                name="delivery",
                module="bot.services.delivery",
                class_names=(
                    "DeliveryService",
                    "Delivery",
                ),
                factory_names=(
                    "create_delivery_service",
                    "create_service",
                ),
                priority=30,
            ),
            ComponentSpec(
                name="verification",
                module="bot.services.verification",
                class_names=(
                    "VerificationService",
                    "Verification",
                ),
                factory_names=(
                    "create_verification_service",
                    "create_service",
                ),
                priority=40,
            ),
            ComponentSpec(
                name="shortener",
                module="bot.services.shortener",
                class_names=(
                    "ShortenerService",
                    "Shortener",
                ),
                factory_names=(
                    "create_shortener_service",
                    "create_service",
                ),
                priority=50,
            ),
            ComponentSpec(
                name="file_search",
                module="bot.services.file_search",
                class_names=(
                    "FileSearchService",
                    "FileSearch",
                ),
                factory_names=(
                    "create_file_search_service",
                    "create_service",
                ),
                priority=60,
            ),
            ComponentSpec(
                name="filter",
                module="bot.services.filter",
                class_names=(
                    "FilterService",
                    "Filter",
                ),
                factory_names=(
                    "create_filter_service",
                    "create_service",
                ),
                priority=70,
            ),
            ComponentSpec(
                name="broadcast",
                module="bot.services.broadcast",
                class_names=(
                    "BroadcastService",
                    "Broadcast",
                ),
                factory_names=(
                    "create_broadcast_service",
                    "create_service",
                ),
                priority=80,
            ),
            ComponentSpec(
                name="moderation",
                module="bot.services.moderation",
                class_names=(
                    "ModerationService",
                    "Moderation",
                ),
                factory_names=(
                    "create_moderation_service",
                    "create_service",
                ),
                priority=90,
            ),
            ComponentSpec(
                name="indexer",
                module="bot.services.indexer",
                class_names=(
                    "IndexerService",
                    "Indexer",
                ),
                factory_names=(
                    "create_indexer_service",
                    "create_service",
                ),
                priority=100,
            ),
        )

    def _default_middleware_specs(
        self,
    ) -> tuple[ComponentSpec, ...]:

        return (
            ComponentSpec(
                name="logging",
                module="bot.middleware.logging",
                class_names=(
                    "LoggingMiddleware",
                ),
                factory_names=(
                    "create_logging_middleware",
                ),
                priority=10,
            ),
            ComponentSpec(
                name="auth",
                module="bot.middleware.auth",
                class_names=(
                    "AuthMiddleware",
                ),
                factory_names=(
                    "create_auth_middleware",
                ),
                priority=20,
            ),
            ComponentSpec(
                name="throttling",
                module="bot.middleware.throttling",
                class_names=(
                    "ThrottlingMiddleware",
                ),
                factory_names=(
                    "create_throttling_middleware",
                ),
                priority=30,
            ),
            ComponentSpec(
                name="admin",
                module="bot.middleware.admin",
                class_names=(
                    "AdminMiddleware",
                ),
                factory_names=(
                    "create_admin_middleware",
                ),
                priority=40,
            ),
            ComponentSpec(
                name="errors",
                module="bot.middleware.errors",
                class_names=(
                    "ErrorMiddleware",
                ),
                factory_names=(
                    "create_error_middleware",
                    "create_error_handler",
                ),
                priority=100,
            ),
        )

    def _default_handler_specs(
        self,
    ) -> tuple[ComponentSpec, ...]:

        return (
            ComponentSpec(
                name="init",
                module="bot.handlers.init",
                class_names=(
                    "InitHandler",
                    "Init",
                ),
                factory_names=(
                    "create_handler",
                    "register",
                ),
                priority=0,
            ),
            ComponentSpec(
                name="start",
                module="bot.handlers.start",
                class_names=(
                    "StartHandler",
                    "Start",
                ),
                factory_names=(
                    "create_handler",
                    "register",
                ),
                priority=10,
            ),
            ComponentSpec(
                name="search",
                module="bot.handlers.search",
                class_names=(
                    "SearchHandler",
                    "Search",
                ),
                factory_names=(
                    "create_handler",
                    "register",
                ),
                priority=20,
            ),
            ComponentSpec(
                name="user",
                module="bot.handlers.user",
                class_names=(
                    "UserHandler",
                    "User",
                ),
                factory_names=(
                    "create_handler",
                    "register",
                ),
                priority=30,
            ),
            ComponentSpec(
                name="admin",
                module="bot.handlers.admin",
                class_names=(
                    "AdminHandler",
                    "Admin",
                ),
                factory_names=(
                    "create_handler",
                    "register",
                ),
                priority=40,
            ),
        )

    # ========================================================================
    # Component resolution
    # ========================================================================

    def _resolve_component(
        self,
        module: Any,
        spec: ComponentSpec,
    ) -> Any:

        # Factory functions are preferred because they can receive
        # application dependencies.
        for factory_name in (
            spec.factory_names
        ):

            factory = getattr(
                module,
                factory_name,
                None,
            )

            if not callable(
                factory
            ):
                continue

            instance = (
                self._call_factory(
                    factory
                )
            )

            if instance is not None:

                return instance

        # Try known class names.
        for class_name in (
            spec.class_names
        ):

            cls = getattr(
                module,
                class_name,
                None,
            )

            if cls is None:
                continue

            if not inspect.isclass(
                cls
            ):
                continue

            instance = (
                self._construct_class(
                    cls
                )
            )

            if instance is not None:

                return instance

        # Some modules expose a singleton called "service".
        for attribute_name in (
            "service",
            "handler",
            "middleware",
            "instance",
        ):

            value = getattr(
                module,
                attribute_name,
                None,
            )

            if value is not None:

                return value

        return None

    def _resolve_handlers(
        self,
        module: Any,
        spec: ComponentSpec,
    ) -> list[Any]:

        components: list[Any] = []

        # First check for a module-level register function.
        register = getattr(
            module,
            "create_handler",
            None,
        )

        if callable(
            register
        ):

            result = self._call_factory(
                register
            )

            if result is not None:

                if isinstance(
                    result,
                    (list, tuple, set),
                ):

                    components.extend(
                        result
                    )

                else:

                    components.append(
                        result
                    )

                return components

        # Check class-based handler.
        instance = self._resolve_component(
            module,
            spec,
        )

        if instance is not None:

            if isinstance(
                instance,
                (list, tuple, set),
            ):

                components.extend(
                    instance
                )

            else:

                components.append(
                    instance
                )

        # Check module-level handler collections.
        for attribute_name in (
            "handlers",
            "HANDLERS",
            "router",
            "ROUTER",
        ):

            value = getattr(
                module,
                attribute_name,
                None,
            )

            if value is None:
                continue

            if isinstance(
                value,
                (list, tuple, set),
            ):

                components.extend(
                    value
                )

            else:

                components.append(
                    value
                )

            break

        return self._deduplicate(
            components
        )

    # ========================================================================
    # Construction helpers
    # ========================================================================

    def _call_factory(
        self,
        factory: Any,
    ) -> Any:

        candidates = (
            {
                "settings": self.settings,
                "container": self.container,
                "database": self.database,
                "redis": self.redis,
                "cache": self.cache,
            },
            {
                "settings": self.settings,
            },
            {},
        )

        for kwargs in candidates:

            try:

                return factory(
                    **self._accepted_kwargs(
                        factory,
                        kwargs,
                    )
                )

            except TypeError as exc:

                # Only retry if the error looks like a function
                # signature mismatch.
                message = str(
                    exc
                ).lower()

                if (
                    "unexpected keyword" not in message
                    and "required positional" not in message
                    and "missing" not in message
                ):

                    raise

        return None

    def _construct_class(
        self,
        cls: type,
    ) -> Any:

        candidates = (
            {
                "settings": self.settings,
                "container": self.container,
                "database": self.database,
                "redis": self.redis,
                "cache": self.cache,
            },
            {
                "settings": self.settings,
            },
            {},
        )

        for kwargs in candidates:

            try:

                accepted = (
                    self._accepted_kwargs(
                        cls,
                        kwargs,
                    )
                )

                return cls(
                    **accepted
                )

            except TypeError as exc:

                message = str(
                    exc
                ).lower()

                if (
                    "unexpected keyword" not in message
                    and "required positional" not in message
                    and "missing" not in message
                ):

                    logger.debug(
                        "Could not construct %s: %s",
                        cls,
                        exc,
                    )

                    return None

        return None

    @staticmethod
    def _accepted_kwargs(
        callable_object: Any,
        values: dict[str, Any],
    ) -> dict[str, Any]:

        try:

            signature = inspect.signature(
                callable_object
            )

        except (
            TypeError,
            ValueError,
        ):

            return values

        parameters = signature.parameters

        if any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):

            return values

        return {
            key: value
            for key, value in values.items()
            if key in parameters
        }

    # ========================================================================
    # Telegram installation
    # ========================================================================

    def install_into_telegram(
        self,
        application: Any,
    ) -> WiringResult:

        if application is None:

            raise ValueError(
                "Telegram application cannot be None."
            )

        self._telegram_application = (
            application
        )

        errors: list[str] = []

        middleware_count = 0

        handler_count = 0

        try:

            middleware_count = (
                self.middleware.install(
                    application
                )
            )

        except Exception as exc:

            errors.append(
                f"Middleware installation failed: {exc}"
            )

        try:

            handler_count = (
                self.handlers.register_all(
                    application
                )
            )

        except Exception as exc:

            errors.append(
                f"Handler registration failed: {exc}"
            )

        # Error handlers can be exposed independently from ordinary
        # middleware, so attempt to register them when present.
        self._install_error_handlers(
            application
        )

        self.state.application_installed = (
            not errors
        )

        return WiringResult(
            success=not errors,
            services=len(
                self.services
            ),
            middleware=middleware_count,
            handlers=handler_count,
            errors=errors,
            details=self.summary(),
        )

    def _install_error_handlers(
        self,
        application: Any,
    ) -> None:

        module = self._import_module(
            "bot.middleware.errors"
        )

        if module is None:
            return

        factory = getattr(
            module,
            "create_error_handler",
            None,
        )

        if not callable(
            factory
        ):
            return

        try:

            handler = (
                self._call_factory(
                    factory
                )
            )

            if handler is not None:

                add_error_handler = getattr(
                    application,
                    "add_error_handler",
                    None,
                )

                if callable(
                    add_error_handler
                ):

                    add_error_handler(
                        handler
                    )

        except Exception:

            logger.exception(
                "Failed to install Telegram error handler."
            )

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(
        self,
    ) -> None:

        if self.state.initialized:
            return

        await self.services.initialize()

        await self.middleware.initialize()

        await self.handlers.initialize()

        self.state.initialized = True

        self.state.shutdown = False

        logger.info(
            "Integration layer initialized."
        )

    # ========================================================================
    # Shutdown
    # ========================================================================

    async def shutdown(
        self,
    ) -> None:

        if self.state.shutdown:
            return

        await self.handlers.shutdown()

        await self.middleware.shutdown()

        await self.services.shutdown()

        self.state.initialized = False

        self.state.shutdown = True

        logger.info(
            "Integration layer shut down."
        )

    # ========================================================================
    # Validation
    # ========================================================================

    def validate(
        self,
    ) -> list[str]:

        errors: list[str] = []

        if self.settings is None:

            errors.append(
                "Settings are missing."
            )

        else:

            try:

                errors.extend(
                    self.settings.validate(
                        raise_on_error=False
                    )
                )

            except Exception as exc:

                errors.append(
                    str(exc)
                )

        try:

            service_health = (
                self.services.summary()
            )

            if (
                service_health["required"]
                > service_health["count"]
            ):

                errors.append(
                    "Invalid required service count."
                )

        except Exception as exc:

            errors.append(
                f"Service registry validation failed: {exc}"
            )

        errors.extend(
            self.handlers.validate()
        )

        errors.extend(
            self.middleware.validate()
        )

        self.state.validated = (
            not errors
        )

        return errors

    # ========================================================================
    # Full checks
    # ========================================================================

    async def check(
        self,
    ) -> dict[str, Any]:

        checker = StartupChecker(
            settings=self.settings,
            container=self.container,
            service_registry=self.services,
            handler_registry=self.handlers,
            middleware_registry=self.middleware,
        )

        return await checker.run()

    async def health(
        self,
    ) -> dict[str, Any]:

        checker = HealthChecker(
            container=self.container,
            service_registry=self.services,
        )

        return await checker.check()

    # ========================================================================
    # Module loading
    # ========================================================================

    def _import_module(
        self,
        module_name: str,
    ) -> Any:

        if module_name in self._loaded_modules:

            return self._loaded_modules[
                module_name
            ]

        try:

            module = importlib.import_module(
                module_name
            )

            self._loaded_modules[
                module_name
            ] = module

            return module

        except ModuleNotFoundError as exc:

            # Missing optional modules are normal during incremental
            # development, so don't crash composition automatically.
            if exc.name == module_name:

                logger.debug(
                    "Optional module unavailable: %s",
                    module_name,
                )

                return None

            logger.exception(
                "Nested import failed for %s.",
                module_name,
            )

            raise

    # ========================================================================
    # Registry helpers
    # ========================================================================

    def middleware_name_exists(
        self,
        name: str,
    ) -> bool:

        try:

            self.middleware.get(
                name
            )

            return True

        except KeyError:

            return False

    def handler_name_exists(
        self,
        name: str,
    ) -> bool:

        try:

            self.handlers.get(
                name,
                required=False,
            )

            return (
                name.lower()
                in {
                    entry.name
                    for entry
                    in self.handlers.entries(
                        enabled_only=False
                    )
                }
            )

        except (
            KeyError,
            AttributeError,
        ):

            return False

    # ========================================================================
    # Utility
    # ========================================================================

    @staticmethod
    def _deduplicate(
        values: Iterable[Any],
    ) -> list[Any]:

        result: list[Any] = []

        seen: set[int] = set()

        for value in values:

            identity = id(
                value
            )

            if identity in seen:
                continue

            seen.add(
                identity
            )

            result.append(
                value
            )

        return result

    # ========================================================================
    # Summary
    # ========================================================================

    def summary(
        self,
    ) -> dict[str, Any]:

        return {
            "state": {
                "services_registered": (
                    self.state.services_registered
                ),
                "middleware_registered": (
                    self.state.middleware_registered
                ),
                "handlers_registered": (
                    self.state.handlers_registered
                ),
                "application_installed": (
                    self.state.application_installed
                ),
                "initialized": (
                    self.state.initialized
                ),
                "shutdown": (
                    self.state.shutdown
                ),
                "validated": (
                    self.state.validated
                ),
            },
            "services": (
                self.services.summary()
            ),
            "middleware": (
                self.middleware.summary()
            ),
            "handlers": (
                self.handlers.summary()
            ),
            "telegram": (
                self._telegram_application
                is not None
            ),
            "modules_loaded": list(
                self._loaded_modules.keys()
            ),
        }


# ============================================================================
# Factory
# ============================================================================

def build_wiring(
    settings: Settings,
    *,
    container: Any = None,
    database: Any = None,
    redis: Any = None,
    cache: Any = None,
    compose: bool = True,
) -> ApplicationWiring:

    wiring = ApplicationWiring(
        settings,
        container=container,
        database=database,
        redis=redis,
        cache=cache,
    )

    if compose:

        result = wiring.compose()

        if not result.success:

            logger.warning(
                "Application wiring completed with errors: %s",
                result.errors,
            )

    return wiring


# ============================================================================
# Complete bootstrap helper
# ============================================================================

async def bootstrap_application(
    settings: Settings,
    *,
    container: Any = None,
    telegram_application: Any = None,
) -> ApplicationWiring:

    wiring = build_wiring(
        settings,
        container=container,
    )

    await wiring.initialize()

    if telegram_application is not None:

        wiring.install_into_telegram(
            telegram_application
        )

    return wiring


__all__ = [
    "ComponentSpec",
    "WiringState",
    "WiringResult",
    "ApplicationWiring",
    "build_wiring",
    "bootstrap_application",
    "DEFAULT_SERVICE_MODULES",
    "DEFAULT_MIDDLEWARE_MODULES",
    "DEFAULT_HANDLER_MODULES",
]