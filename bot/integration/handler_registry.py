"""
bot.integration.handler_registry

Telegram handler registration and validation.

The registry keeps handler ordering explicit and allows the application
bootstrap to register all existing handlers consistently.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(
    "bot.integration.handlers"
)


@dataclass(slots=True)
class HandlerEntry:

    name: str

    handler: Any

    group: int = 0

    priority: int = 100

    enabled: bool = True

    registered: bool = False

    metadata: dict[str, Any] = None

    def __post_init__(
        self,
    ) -> None:

        if self.metadata is None:
            self.metadata = {}


class HandlerRegistry:

    def __init__(self) -> None:

        self._entries: dict[
            str,
            HandlerEntry,
        ] = {}

    # ========================================================================
    # Registration
    # ========================================================================

    def register(
        self,
        name: str,
        handler: Any,
        *,
        group: int = 0,
        priority: int = 100,
        enabled: bool = True,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        replace: bool = False,
    ) -> HandlerEntry:

        key = self._normalize(
            name
        )

        if (
            key in self._entries
            and not replace
        ):

            raise ValueError(
                f"Handler '{key}' already registered."
            )

        entry = HandlerEntry(
            name=key,
            handler=handler,
            group=int(group),
            priority=int(priority),
            enabled=bool(enabled),
            metadata=dict(
                metadata
                or {}
            ),
        )

        self._entries[key] = entry

        return entry

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
                    f"Handler '{key}' is not registered."
                )

            return None

        return entry.handler

    def entries(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[HandlerEntry]:

        values = list(
            self._entries.values()
        )

        if enabled_only:

            values = [
                entry
                for entry in values
                if entry.enabled
            ]

        return sorted(
            values,
            key=lambda entry: (
                entry.group,
                entry.priority,
                entry.name,
            ),
        )

    # ========================================================================
    # Telegram registration
    # ========================================================================

    def register_all(
        self,
        application: Any,
    ) -> int:

        if application is None:

            raise ValueError(
                "Telegram application cannot be None."
            )

        count = 0

        for entry in self.entries():

            self._register_one(
                application,
                entry,
            )

            count += 1

        return count

    @staticmethod
    def _register_one(
        application: Any,
        entry: HandlerEntry,
    ) -> None:

        handler = entry.handler

        if hasattr(
            application,
            "add_handler",
        ):

            application.add_handler(
                handler,
                group=entry.group,
            )

            entry.registered = True

            logger.debug(
                "Registered Telegram handler: %s",
                entry.name,
            )

            return

        raise TypeError(
            "Application does not support add_handler()."
        )

    # ========================================================================
    # Lifecycle
    # ========================================================================

    async def initialize(
        self,
    ) -> None:

        for entry in self._entries.values():

            initializer = getattr(
                entry.handler,
                "initialize",
                None,
            )

            if callable(
                initializer
            ):

                result = initializer()

                if inspect.isawaitable(
                    result
                ):

                    await result

    async def shutdown(
        self,
    ) -> None:

        for entry in reversed(
            self.entries(
                enabled_only=False
            )
        ):

            for method_name in (
                "shutdown",
                "close",
                "stop",
            ):

                method = getattr(
                    entry.handler,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                try:

                    result = method()

                    if inspect.isawaitable(
                        result
                    ):

                        await result

                except Exception:

                    logger.exception(
                        "Handler shutdown failed: %s",
                        entry.name,
                    )

                break

    # ========================================================================
    # Validation
    # ========================================================================

    def validate(
        self,
    ) -> list[str]:

        errors: list[str] = []

        for entry in self._entries.values():

            if not entry.enabled:
                continue

            if entry.handler is None:

                errors.append(
                    f"Handler '{entry.name}' has no implementation."
                )

                continue

            if not callable(
                getattr(
                    entry.handler,
                    "check_update",
                    None,
                )
            ):

                # Telegram handler objects normally expose
                # check_update. Custom wrappers may not.
                logger.debug(
                    "Handler '%s' does not expose check_update().",
                    entry.name,
                )

        return errors

    # ========================================================================
    # State
    # ========================================================================

    def enable(
        self,
        name: str,
    ) -> None:

        self._entries[
            self._normalize(name)
        ].enabled = True

    def disable(
        self,
        name: str,
    ) -> None:

        self._entries[
            self._normalize(name)
        ].enabled = False

    def remove(
        self,
        name: str,
    ) -> Any:

        entry = self._entries.pop(
            self._normalize(name),
            None,
        )

        return (
            entry.handler
            if entry
            else None
        )

    def clear(
        self,
    ) -> None:

        self._entries.clear()

    def summary(
        self,
    ) -> dict[str, Any]:

        return {
            "count": len(
                self._entries
            ),
            "enabled": sum(
                1
                for entry in self._entries.values()
                if entry.enabled
            ),
            "registered": sum(
                1
                for entry in self._entries.values()
                if entry.registered
            ),
            "handlers": {
                entry.name: {
                    "group": entry.group,
                    "priority": entry.priority,
                    "enabled": entry.enabled,
                    "registered": entry.registered,
                }
                for entry in self._entries.values()
            },
        }

    @staticmethod
    def _normalize(
        name: str,
    ) -> str:

        if not isinstance(
            name,
            str,
        ):

            raise TypeError(
                "Handler name must be a string."
            )

        value = name.strip().lower()

        if not value:

            raise ValueError(
                "Handler name cannot be empty."
            )

        return value


__all__ = [
    "HandlerEntry",
    "HandlerRegistry",
]