"""
bot.integration.health

Application health checks.

Health is separated from readiness:
    health  -> process is alive
    readiness -> required dependencies are usable
"""

from __future__ import annotations

import inspect
import time
from typing import Any


class HealthChecker:

    def __init__(
        self,
        *,
        container: Any = None,
        service_registry: Any = None,
    ) -> None:

        self.container = container

        self.service_registry = (
            service_registry
        )

    async def check(
        self,
    ) -> dict[str, Any]:

        started = time.perf_counter()

        checks: dict[
            str,
            Any,
        ] = {}

        checks["process"] = {
            "healthy": True,
            "status": "ok",
        }

        if self.container is not None:

            checks["container"] = {
                "healthy": bool(
                    getattr(
                        self.container,
                        "ready",
                        False,
                    )
                ),
                "status": (
                    "ok"
                    if getattr(
                        self.container,
                        "ready",
                        False,
                    )
                    else "not_ready"
                ),
            }

        if self.service_registry is not None:

            checks["services"] = (
                await self.service_registry.health()
            )

        healthy = all(
            self._healthy(
                value
            )
            for value in checks.values()
        )

        elapsed = (
            time.perf_counter()
            - started
        )

        return {
            "healthy": healthy,
            "status": (
                "ok"
                if healthy
                else "degraded"
            ),
            "latency_ms": round(
                elapsed * 1000,
                2,
            ),
            "checks": checks,
        }

    async def readiness(
        self,
    ) -> dict[str, Any]:

        result = await self.check()

        return {
            "ready": bool(
                result["healthy"]
            ),
            "status": result["status"],
            "checks": result["checks"],
            "latency_ms": result[
                "latency_ms"
            ],
        }

    async def liveness(
        self,
    ) -> dict[str, Any]:

        return {
            "alive": True,
            "status": "ok",
        }

    @staticmethod
    def _healthy(
        value: Any,
    ) -> bool:

        if isinstance(
            value,
            dict,
        ):

            if "healthy" in value:
                return bool(
                    value["healthy"]
                )

            if "ready" in value:
                return bool(
                    value["ready"]
                )

            if "status" in value:
                return value["status"] == "ok"

        return bool(value)


async def check_component(
    component: Any,
) -> dict[str, Any]:

    if component is None:

        return {
            "healthy": False,
            "status": "missing",
        }

    method = getattr(
        component,
        "health",
        None,
    )

    if not callable(
        method
    ):

        return {
            "healthy": True,
            "status": "unknown",
        }

    try:

        result = method()

        if inspect.isawaitable(
            result
        ):

            result = await result

        if isinstance(
            result,
            dict,
        ):

            return result

        return {
            "healthy": bool(result),
            "status": (
                "ok"
                if result
                else "error"
            ),
        }

    except Exception as exc:

        return {
            "healthy": False,
            "status": "error",
            "error": str(exc),
        }


__all__ = [
    "HealthChecker",
    "check_component",
]