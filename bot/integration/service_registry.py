"""
bot.integration.service_registry

Central service registry.

This registry provides:
    - deterministic service registration
    - duplicate protection
    - dependency lookup
    - lifecycle initialization
    - lifecycle shutdown
    - health inspection
    - feature-aware service activation

Services should be created by the application composition layer
and registered here.

This module does not implement service business logic.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Optional


logger = logging.getLogger(
    "bot.integration.services"
)


# ============================================================================
# Service metadata
# ============================================================================

@dataclass(slots=True)
class ServiceEntry:

    name: str

    instance: Any

    enabled: bool = True

    required: bool = False

    priority: int = 100

    dependencies: tuple[str, ...] = ()

    initialized: bool = False

    healthy: bool = False

    error: Optional[str] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# Service registry
# ============================================================================

class ServiceRegistry:

    def __init__(self) -> None:

        self._entries: dict[
            str,
            ServiceEntry,
        ] = {}

        self._initializing = False

        self._initialized = False

    # ========================================================================
    # Registration
    # ========================================================================

    def register(
        self,
        name: str,
        instance: Any,
        *,
        enabled: bool = True,
        required: bool = False,
        priority: int = 100,
        dependencies: tuple[str, ...] = (),
        metadata: Optional[
            dict[str, Any]
        ] = None,
        replace: bool = False,
    ) -> ServiceEntry:

        key = self._normalize(
            name
        )

        if (
            key in self._entries
            and not replace
        ):

            raise ValueError(
                f"Service '{key}' already exists."
            )

        normalized_dependencies = tuple(
            self._normalize(
                dependency
            )
            for dependency in dependencies
        )

        entry = ServiceEntry(
            name=key,
            instance=instance,
            enabled=bool(enabled),
            required=bool(required),
            priority=int(priority),
            dependencies=(
                normalized_dependencies
            ),
            metadata=dict(
                metadata
                or {}
            ),
        )

        self._entries[key] = entry

        return entry

    def unregister(
        self,
        name: str,
    ) -> Any:

        key = self._normalize(
            name
        )

        entry = self._entries.pop(
            key,
            None,
        )

        if entry is None:
            return None

        return entry.instance

    # ========================================================================
    # Lookup
    # ========================================================================

    def get(
        self,
        name: str,
        *,
        required: bool = True,
    ) -> Any:

        key = self._normalize(
            name
        )

        entry = self._entries.get(
            key
        )

        if entry is None:

            if required:
                raise KeyError(
                    f"Service '{key}' is not registered."
                )

            return None

        if (
            not entry.enabled
            and required
        ):

            raise RuntimeError(
                f"Service '{key}' is disabled."
            )

        return entry.instance

    def entry(
        self,
        name: str,
    ) -> ServiceEntry:

        key = self._normalize(
            name
        )

        try:
            return self._entries[key]
        except KeyError as exc:
            raise KeyError(
                f"Service '{key}' is not registered."
            ) from exc

    def contains(
        self,
        name: str,
    ) -> bool:

        return (
            self._normalize(name)
            in self._entries
        )

    # ========================================================================
    # Ordering
    # ========================================================================

    def ordered_entries(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[ServiceEntry]:

        entries = list(
            self._entries.values()
        )

        if enabled_only:

            entries = [
                entry
                for entry in entries
                if entry.enabled
            ]

        return sorted(
            entries,
            key=lambda entry: (
                entry.priority,
                entry.name,
            ),
        )

    # ========================================================================
    # Dependency ordering
    # ========================================================================

    def dependency_order(
        self,
    ) -> list[ServiceEntry]:

        active = {
            entry.name: entry
            for entry in self._entries.values()
            if entry.enabled
        }

        result: list[ServiceEntry] = []

        visiting: set[str] = set()

        visited: set[str] = set()

        def visit(
            name: str,
        ) -> None:

            if name in visited:
                return

            if name in visiting:

                raise RuntimeError(
                    "Circular service dependency detected: "
                    f"{name}"
                )

            entry = active.get(
                name
            )

            if entry is None:
                return

            visiting.add(
                name
            )

            for dependency in (
                entry.dependencies
            ):

                if dependency not in active:

                    if entry.required:

                        raise RuntimeError(
                            f"Required dependency "
                            f"'{dependency}' for service "
                            f"'{name}' is unavailable."
                        )

                    continue

                visit(
                    dependency
                )

            visiting.remove(
                name
            )

            visited.add(
                name
            )

            result.append(
                entry
            )

        for name in active:
            visit(name)

        return result

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(
        self,
    ) -> None:

        if self._initialized:
            return

        if self._initializing:
            raise RuntimeError(
                "Service registry is already initializing."
            )

        self._initializing = True

        logger.info(
            "Initializing %d services.",
            len(
                self._entries
            ),
        )

        try:

            for entry in self.dependency_order():

                await self._initialize_entry(
                    entry
                )

            self._initialized = True

        finally:

            self._initializing = False

    async def _initialize_entry(
        self,
        entry: ServiceEntry,
    ) -> None:

        if not entry.enabled:
            return

        if entry.initialized:
            return

        try:

            for dependency in (
                entry.dependencies
            ):

                dependency_entry = (
                    self._entries.get(
                        dependency
                    )
                )

                if (
                    dependency_entry is not None
                    and dependency_entry.enabled
                    and not dependency_entry.initialized
                ):

                    raise RuntimeError(
                        f"Dependency '{dependency}' "
                        f"for '{entry.name}' was not initialized."
                    )

            method = self._find_lifecycle_method(
                entry.instance,
                (
                    "initialize",
                    "init",
                    "start",
                ),
            )

            if method is not None:

                result = method()

                if inspect.isawaitable(
                    result
                ):

                    await result

            entry.initialized = True

            entry.healthy = True

            entry.error = None

            logger.info(
                "Service initialized: %s",
                entry.name,
            )

        except Exception as exc:

            entry.initialized = False

            entry.healthy = False

            entry.error = str(
                exc
            )

            logger.exception(
                "Service initialization failed: %s",
                entry.name,
            )

            if entry.required:
                raise

    # ========================================================================
    # Shutdown
    # ========================================================================

    async def shutdown(
        self,
    ) -> None:

        if not self._entries:
            return

        logger.info(
            "Shutting down services."
        )

        for entry in reversed(
            self.dependency_order()
        ):

            if not entry.initialized:
                continue

            try:

                method = self._find_lifecycle_method(
                    entry.instance,
                    (
                        "shutdown",
                        "close",
                        "stop",
                    ),
                )

                if method is not None:

                    result = method()

                    if inspect.isawaitable(
                        result
                    ):

                        await result

                entry.initialized = False

                entry.healthy = False

            except Exception as exc:

                entry.error = str(
                    exc
                )

                logger.exception(
                    "Service shutdown failed: %s",
                    entry.name,
                )

        self._initialized = False

    # ========================================================================
    # Health
    # ========================================================================

    async def health(
        self,
    ) -> dict[str, Any]:

        services: dict[
            str,
            dict[str, Any],
        ] = {}

        overall = True

        for entry in self._entries.values():

            healthy = entry.healthy

            health_method = (
                getattr(
                    entry.instance,
                    "health",
                    None,
                )
            )

            if (
                callable(
                    health_method
                )
            ):

                try:

                    result = health_method()

                    if inspect.isawaitable(
                        result
                    ):

                        result = await result

                    if isinstance(
                        result,
                        dict,
                    ):

                        healthy = bool(
                            result.get(
                                "healthy",
                                result.get(
                                    "status"
                                ) == "ok",
                            )
                        )

                    else:

                        healthy = bool(
                            result
                        )

                except Exception as exc:

                    healthy = False

                    entry.error = str(
                        exc
                    )

            if (
                entry.required
                and entry.enabled
                and not healthy
            ):

                overall = False

            services[
                entry.name
            ] = {
                "enabled": entry.enabled,
                "required": entry.required,
                "initialized": entry.initialized,
                "healthy": healthy,
                "error": entry.error,
            }

        return {
            "healthy": overall,
            "initialized": self._initialized,
            "services": services,
        }

    # ========================================================================
    # Helpers
    # ========================================================================

    @staticmethod
    def _find_lifecycle_method(
        instance: Any,
        names: tuple[str, ...],
    ) -> Any:

        if instance is None:
            return None

        for name in names:

            method = getattr(
                instance,
                name,
                None,
            )

            if callable(method):
                return method

        return None

    @staticmethod
    def _normalize(
        name: str,
    ) -> str:

        if not isinstance(
            name,
            str,
        ):

            raise TypeError(
                "Service name must be a string."
            )

        value = name.strip().lower()

        if not value:

            raise ValueError(
                "Service name cannot be empty."
            )

        return value

    # ========================================================================
    # Introspection
    # ========================================================================

    def names(
        self,
    ) -> tuple[str, ...]:

        return tuple(
            self._entries.keys()
        )

    def enabled_names(
        self,
    ) -> tuple[str, ...]:

        return tuple(
            entry.name
            for entry in self._entries.values()
            if entry.enabled
        )

    def required_names(
        self,
    ) -> tuple[str, ...]:

        return tuple(
            entry.name
            for entry in self._entries.values()
            if entry.required
        )

    def summary(
        self,
    ) -> dict[str, Any]:

        return {
            "count": len(
                self._entries
            ),
            "enabled": len(
                self.enabled_names()
            ),
            "required": len(
                self.required_names()
            ),
            "initialized": self._initialized,
            "services": {
                entry.name: {
                    "enabled": entry.enabled,
                    "required": entry.required,
                    "priority": entry.priority,
                    "dependencies": (
                        list(
                            entry.dependencies
                        )
                    ),
                    "initialized": entry.initialized,
                    "healthy": entry.healthy,
                    "error": entry.error,
                }
                for entry in self._entries.values()
            },
        }

    def clear(
        self,
    ) -> None:

        self._entries.clear()

        self._initialized = False

    def __len__(
        self,
    ) -> int:

        return len(
            self._entries
        )

    def __contains__(
        self,
        name: str,
    ) -> bool:

        return self.contains(
            name
        )


__all__ = [
    "ServiceEntry",
    "ServiceRegistry",
]