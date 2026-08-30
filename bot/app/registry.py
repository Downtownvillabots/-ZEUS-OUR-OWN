"""
bot.app.registry

Handler and application component registry.

The registry provides deterministic registration order and prevents
accidental duplicate Telegram handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(
    "bot.app.registry"
)


@dataclass(slots=True)
class RegisteredComponent:

    name: str

    component: Any

    priority: int = 100

    enabled: bool = True


class ComponentRegistry:

    def __init__(self) -> None:

        self._components: dict[
            str,
            RegisteredComponent,
        ] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        component: Any,
        *,
        priority: int = 100,
        enabled: bool = True,
        replace: bool = False,
    ) -> RegisteredComponent:

        key = self._normalize(
            name
        )

        if (
            key in self._components
            and not replace
        ):

            raise ValueError(
                f"Component '{key}' already registered."
            )

        item = RegisteredComponent(
            name=key,
            component=component,
            priority=int(priority),
            enabled=bool(enabled),
        )

        self._components[key] = item

        return item

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(
        self,
        name: str,
        *,
        required: bool = True,
    ) -> Any:

        key = self._normalize(
            name
        )

        item = self._components.get(
            key
        )

        if item is None:

            if required:
                raise KeyError(
                    f"Component '{key}' not registered."
                )

            return None

        return item.component

    def get_entry(
        self,
        name: str,
    ) -> RegisteredComponent:

        key = self._normalize(
            name
        )

        return self._components[key]

    # ------------------------------------------------------------------
    # Ordering
    # ------------------------------------------------------------------

    def entries(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[
        RegisteredComponent
    ]:

        values = list(
            self._components.values()
        )

        if enabled_only:

            values = [
                item
                for item in values
                if item.enabled
            ]

        return sorted(
            values,
            key=lambda item: (
                item.priority,
                item.name,
            ),
        )

    def components(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[Any]:

        return [
            item.component
            for item in self.entries(
                enabled_only=enabled_only
            )
        ]

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def enable(
        self,
        name: str,
    ) -> None:

        self.get_entry(
            name
        ).enabled = True

    def disable(
        self,
        name: str,
    ) -> None:

        self.get_entry(
            name
        ).enabled = False

    def remove(
        self,
        name: str,
    ) -> Any:

        key = self._normalize(
            name
        )

        item = self._components.pop(
            key,
            None,
        )

        return (
            item.component
            if item
            else None
        )

    def clear(self) -> None:

        self._components.clear()

    def __contains__(
        self,
        name: str,
    ) -> bool:

        return (
            self._normalize(name)
            in self._components
        )

    def __len__(
        self,
    ) -> int:

        return len(
            self._components
        )

    @staticmethod
    def _normalize(
        name: str,
    ) -> str:

        if not isinstance(
            name,
            str,
        ):
            raise TypeError(
                "Component name must be a string."
            )

        value = name.strip().lower()

        if not value:
            raise ValueError(
                "Component name cannot be empty."
            )

        return value


# ============================================================================
# Telegram handler registry
# ============================================================================

class HandlerRegistry(
    ComponentRegistry
):

    def register_handler(
        self,
        name: str,
        handler: Any,
        *,
        priority: int = 100,
        enabled: bool = True,
        replace: bool = False,
    ) -> RegisteredComponent:

        return self.register(
            name,
            handler,
            priority=priority,
            enabled=enabled,
            replace=replace,
        )

    def handlers(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[Any]:

        return self.components(
            enabled_only=enabled_only
        )


# ============================================================================
# Service registry
# ============================================================================

class ServiceRegistry(
    ComponentRegistry
):

    def register_service(
        self,
        name: str,
        service: Any,
        *,
        priority: int = 100,
        enabled: bool = True,
        replace: bool = False,
    ) -> RegisteredComponent:

        return self.register(
            name,
            service,
            priority=priority,
            enabled=enabled,
            replace=replace,
        )

    def services(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[Any]:

        return self.components(
            enabled_only=enabled_only
        )


# ============================================================================
# Global registry
# ============================================================================

_global_registry: Optional[
    ComponentRegistry
] = None


def get_registry() -> ComponentRegistry:

    global _global_registry

    if _global_registry is None:
        _global_registry = (
            ComponentRegistry()
        )

    return _global_registry


def reset_registry() -> None:

    global _global_registry

    if _global_registry is not None:
        _global_registry.clear()

    _global_registry = None


__all__ = [
    "RegisteredComponent",
    "ComponentRegistry",
    "HandlerRegistry",
    "ServiceRegistry",
    "get_registry",
    "reset_registry",
]