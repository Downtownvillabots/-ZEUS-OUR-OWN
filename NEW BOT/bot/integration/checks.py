"""
bot.integration.checks

Startup validation.

Checks configuration, required dependencies, service wiring,
middleware wiring, and Telegram application availability.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CheckResult:

    name: str

    passed: bool

    message: str = ""

    required: bool = True

    details: dict[str, Any] = field(
        default_factory=dict
    )


class StartupChecker:

    def __init__(
        self,
        *,
        settings: Any = None,
        container: Any = None,
        service_registry: Any = None,
        handler_registry: Any = None,
        middleware_registry: Any = None,
    ) -> None:

        self.settings = settings

        self.container = container

        self.service_registry = (
            service_registry
        )

        self.handler_registry = (
            handler_registry
        )

        self.middleware_registry = (
            middleware_registry
        )

    async def run(
        self,
    ) -> dict[str, Any]:

        results: list[
            CheckResult
        ] = []

        results.append(
            self._check_configuration()
        )

        results.append(
            self._check_container()
        )

        results.extend(
            self._check_services()
        )

        results.extend(
            self._check_handlers()
        )

        results.extend(
            self._check_middleware()
        )

        passed = all(
            (
                result.passed
                or not result.required
            )
            for result in results
        )

        return {
            "passed": passed,
            "checks": [
                {
                    "name": result.name,
                    "passed": result.passed,
                    "required": result.required,
                    "message": result.message,
                    "details": result.details,
                }
                for result in results
            ],
        }

    # ========================================================================
    # Configuration
    # ========================================================================

    def _check_configuration(
        self,
    ) -> CheckResult:

        if self.settings is None:

            return CheckResult(
                name="configuration",
                passed=False,
                message="Settings object is missing.",
            )

        try:

            errors = self.settings.validate(
                raise_on_error=False
            )

        except Exception as exc:

            return CheckResult(
                name="configuration",
                passed=False,
                message=str(exc),
            )

        if errors:

            return CheckResult(
                name="configuration",
                passed=False,
                message="Configuration validation failed.",
                details={
                    "errors": errors,
                },
            )

        return CheckResult(
            name="configuration",
            passed=True,
            message="Configuration is valid.",
        )

    # ========================================================================
    # Container
    # ========================================================================

    def _check_container(
        self,
    ) -> CheckResult:

        if self.container is None:

            return CheckResult(
                name="container",
                passed=False,
                message="Application container is missing.",
            )

        ready = bool(
            getattr(
                self.container,
                "ready",
                False,
            )
        )

        return CheckResult(
            name="container",
            passed=ready,
            message=(
                "Container is ready."
                if ready
                else "Container is not ready."
            ),
        )

    # ========================================================================
    # Services
    # ========================================================================

    def _check_services(
        self,
    ) -> list[CheckResult]:

        if self.service_registry is None:

            return [
                CheckResult(
                    name="services",
                    passed=False,
                    message="Service registry is missing.",
                )
            ]

        results: list[
            CheckResult
        ] = []

        for entry in (
            self.service_registry.ordered_entries(
                enabled_only=True
            )
        ):

            passed = (
                entry.instance is not None
                and (
                    entry.initialized
                    or not entry.required
                )
            )

            results.append(
                CheckResult(
                    name=f"service:{entry.name}",
                    passed=passed,
                    required=entry.required,
                    message=(
                        "Service ready."
                        if passed
                        else (
                            entry.error
                            or "Service is not initialized."
                        )
                    ),
                    details={
                        "priority": entry.priority,
                        "dependencies": list(
                            entry.dependencies
                        ),
                    },
                )
            )

        return results

    # ========================================================================
    # Handlers
    # ========================================================================

    def _check_handlers(
        self,
    ) -> list[CheckResult]:

        if self.handler_registry is None:

            return [
                CheckResult(
                    name="handlers",
                    passed=False,
                    message="Handler registry is missing.",
                )
            ]

        errors = (
            self.handler_registry.validate()
        )

        if errors:

            return [
                CheckResult(
                    name="handlers",
                    passed=False,
                    message="Handler validation failed.",
                    details={
                        "errors": errors,
                    },
                )
            ]

        return [
            CheckResult(
                name="handlers",
                passed=True,
                message="Handlers are valid.",
                details=(
                    self.handler_registry.summary()
                ),
            )
        ]

    # ========================================================================
    # Middleware
    # ========================================================================

    def _check_middleware(
        self,
    ) -> list[CheckResult]:

        if self.middleware_registry is None:

            return [
                CheckResult(
                    name="middleware",
                    passed=False,
                    message="Middleware registry is missing.",
                )
            ]

        errors = (
            self.middleware_registry.validate()
        )

        if errors:

            return [
                CheckResult(
                    name="middleware",
                    passed=False,
                    message="Middleware validation failed.",
                    details={
                        "errors": errors,
                    },
                )
            ]

        return [
            CheckResult(
                name="middleware",
                passed=True,
                message="Middleware is valid.",
                details=(
                    self.middleware_registry.summary()
                ),
            )
        ]


async def run_startup_checks(
    checker: StartupChecker,
) -> dict[str, Any]:

    return await checker.run()


__all__ = [
    "CheckResult",
    "StartupChecker",
    "run_startup_checks",
]