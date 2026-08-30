"""
bot.integration.middleware_registry

Middleware composition registry.

Middleware order matters. Lower priority values execute earlier.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(
    "bot.integration.middleware"
)


@dataclass(slots=True)
class MiddlewareEntry:

    name: str

    middleware: Any

    priority: int = 100

    enabled: bool = True

    installed: bool = False


class MiddlewareRegistry:

    def __init__(self) -> None:

        self._entries: dict[
            str,
            MiddlewareEntry,
        ] = {}

    def register(
        self,
        name: str,
        middleware: Any,
        *,
        priority: int = 100,
        enabled: bool = True,
        replace: bool = False,
    ) -> MiddlewareEntry:

        key = self._normalize(
            name
        )

        if (
            key in self._entries
            and not replace
        ):

            raise ValueError(
                f"Middleware '{key}' already registered."
            )

        entry = MiddlewareEntry(
            name=key,
            middleware=middleware,
            priority=int(priority),
            enabled=bool(enabled),
        )

        self._entries[key] = entry

        return entry

    def get(
        self,
        name: str,
    ) -> Any:

        return self._entries[
            self._normalize(name)
        ].middleware

    def entries(
        self,
        *,
        enabled_only: bool = True,
    ) -> list[MiddlewareEntry]:

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

    async def initialize(
        self,
    ) -> None:

        for entry in self.entries():

            for method_name in (
                "initialize",
                "init",
                "start",
            ):

                method = getattr(
                    entry.middleware,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                result = method()

                if inspect.isawaitable(
                    result
                ):

                    await result

                break

    def install(
        self,
        application: Any,
    ) -> int:

        count = 0

        for entry in self.entries():

            middleware = (
                entry.middleware
            )

            installed = False

            for method_name in (
                "install",
                "register",
                "attach",
            ):

                method = getattr(
                    middleware,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                result = method(
                    application
                )

                if inspect.isawaitable(
                    result
                ):

                    raise RuntimeError(
                        f"Middleware '{entry.name}' "
                        "has an async install method. "
                        "Install it during async startup."
                    )

                installed = True

                break

            if installed:

                entry.installed = True

                count += 1

        return count

    async def install_async(
        self,
        application: Any,
    ) -> int:

        count = 0

        for entry in self.entries():

            middleware = (
                entry.middleware
            )

            for method_name in (
                "install",
                "register",
                "attach",
            ):

                method = getattr(
                    middleware,
                    method_name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                result = method(
                    application
                )

                if inspect.isawaitable(
                    result
                ):

                    await result

                entry.installed = True

                count += 1

                break

        return count

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
                    entry.middleware,
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
                        "Middleware shutdown failed: %s",
                        entry.name,
                    )

                break

    def validate(
        self,
    ) -> list[str]:

        errors: list[str] = []

        for entry in self._entries.values():

            if not entry.enabled:
                continue

            if entry.middleware is None:

                errors.append(
                    f"Middleware '{entry.name}' "
                    "has no implementation."
                )

        return errors

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
            entry.middleware
            if entry
            else None
        )

    def summary(
        self,
    ) -> dict[str, Any]:

        return {
            "count": len(
                self._entries
            ),
            "enabled": sum(
                entry.enabled
                for entry in self._entries.values()
            ),
            "installed": sum(
                entry.installed
                for entry in self._entries.values()
            ),
            "middleware": {
                entry.name: {
                    "priority": entry.priority,
                    "enabled": entry.enabled,
                    "installed": entry.installed,
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
                "Middleware name must be a string."
            )

        value = name.strip().lower()

        if not value:

            raise ValueError(
                "Middleware name cannot be empty."
            )

        return value


__all__ = [
    "MiddlewareEntry",
    "MiddlewareRegistry",
]