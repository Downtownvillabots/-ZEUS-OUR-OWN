"""
healthcheck.py

Process-level health/readiness entrypoint.

Examples:

    python healthcheck.py
    python healthcheck.py --liveness
    python healthcheck.py --readiness

Exit codes:

    0 = healthy / ready
    1 = unhealthy / not ready
    2 = invalid invocation

This module is intentionally lightweight. It should be safe to invoke
from Docker, Kubernetes, systemd, CI, or a process supervisor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any


EXIT_OK = 0
EXIT_UNHEALTHY = 1
EXIT_INVALID = 2


# ============================================================================
# Result model
# ============================================================================

@dataclass(slots=True)
class HealthResult:

    healthy: bool

    status: str

    details: dict[str, Any]

    exit_code: int

    @classmethod
    def ok(
        cls,
        details: dict[str, Any] | None = None,
    ) -> "HealthResult":

        return cls(
            healthy=True,
            status="ok",
            details=details or {},
            exit_code=EXIT_OK,
        )

    @classmethod
    def failed(
        cls,
        status: str = "unhealthy",
        details: dict[str, Any] | None = None,
    ) -> "HealthResult":

        return cls(
            healthy=False,
            status=status,
            details=details or {},
            exit_code=EXIT_UNHEALTHY,
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "healthy": self.healthy,
            "status": self.status,
            "details": self.details,
        }


# ============================================================================
# Environment helpers
# ============================================================================

def environment_name() -> str:

    return os.getenv(
        "ENVIRONMENT",
        "unknown",
    ).strip() or "unknown"


def process_id() -> int:

    return os.getpid()


def python_version() -> str:

    return (
        f"{sys.version_info.major}."
        f"{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )


# ============================================================================
# Liveness
# ============================================================================

async def check_liveness() -> HealthResult:
    """
    Liveness indicates that the Python process is alive and the health
    command itself can execute.

    It deliberately does not require the database or external services.
    """

    return HealthResult.ok(
        {
            "check": "liveness",
            "process_id": process_id(),
            "python_version": python_version(),
            "environment": environment_name(),
        }
    )


# ============================================================================
# Configuration check
# ============================================================================

def check_configuration() -> HealthResult:

    try:

        from bot.core.config import (
            get_settings,
        )

        settings = get_settings()

        try:

            result = settings.validate(
                raise_on_error=False
            )

        except TypeError:

            result = settings.validate()

        if result:

            if isinstance(
                result,
                (list, tuple),
            ):

                errors = [
                    str(item)
                    for item in result
                ]

            else:

                errors = [
                    str(result)
                ]

            return HealthResult.failed(
                status="configuration_error",
                details={
                    "errors": errors,
                },
            )

        return HealthResult.ok(
            {
                "check": "configuration",
            }
        )

    except Exception as exc:

        return HealthResult.failed(
            status="configuration_error",
            details={
                "error": str(exc),
            },
        )


# ============================================================================
# Application health
# ============================================================================

async def check_application() -> HealthResult:
    """
    Build the application's dependency graph and execute its health checks.

    This does not start Telegram polling.
    """

    try:

        from bot.app.startup import (
            create_application,
        )

        application = (
            create_application()
        )

        # The integration health checker is used when available.
        try:

            from bot.integration.wiring import (
                build_wiring,
            )

            wiring = build_wiring(
                application.settings,
                container=(
                    application.container
                ),
                compose=True,
            )

            result = await wiring.health()

            healthy = bool(
                result.get(
                    "healthy",
                    False,
                )
            )

            return (
                HealthResult.ok(
                    result
                )
                if healthy
                else HealthResult.failed(
                    status="application_unhealthy",
                    details=result,
                )
            )

        except ImportError:

            # Fall back to the application's own health method.
            result = application.health()

            healthy = (
                result.get(
                    "status"
                )
                == "ok"
            )

            return (
                HealthResult.ok(
                    result
                )
                if healthy
                else HealthResult.failed(
                    status="application_not_ready",
                    details=result,
                )
            )

    except Exception as exc:

        return HealthResult.failed(
            status="application_error",
            details={
                "error": str(exc),
            },
        )


# ============================================================================
# Readiness
# ============================================================================

async def check_readiness() -> HealthResult:
    """
    Readiness verifies that the application can accept traffic/work.

    Unlike liveness, readiness may fail when a dependency is unavailable.
    """

    configuration = (
        check_configuration()
    )

    if not configuration.healthy:

        return configuration

    application = await check_application()

    if not application.healthy:

        return application

    return HealthResult.ok(
        {
            "check": "readiness",
            "configuration": (
                configuration.as_dict()
            ),
            "application": (
                application.as_dict()
            ),
        }
    )


# ============================================================================
# Complete health check
# ============================================================================

async def check_health() -> HealthResult:

    liveness = await check_liveness()

    if not liveness.healthy:

        return liveness

    readiness = await check_readiness()

    if not readiness.healthy:

        return readiness

    return HealthResult.ok(
        {
            "liveness": (
                liveness.as_dict()
            ),
            "readiness": (
                readiness.as_dict()
            ),
        }
    )


# ============================================================================
# CLI parser
# ============================================================================

def create_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "Health and readiness checks "
            "for the Telegram bot."
        )
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--liveness",
        action="store_true",
        help="Only verify that the process environment is alive.",
    )

    mode.add_argument(
        "--readiness",
        action="store_true",
        help="Verify configuration and application readiness.",
    )

    mode.add_argument(
        "--health",
        action="store_true",
        help="Run the complete health check.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress normal output; only return the exit code.",
    )

    return parser


# ============================================================================
# CLI execution
# ============================================================================

async def execute(
    *,
    liveness: bool = False,
    readiness: bool = False,
) -> HealthResult:

    if liveness:

        return await check_liveness()

    if readiness:

        return await check_readiness()

    return await check_health()


def render_result(
    result: HealthResult,
    *,
    as_json: bool,
) -> str:

    if as_json:

        return json.dumps(
            result.as_dict(),
            indent=2,
            sort_keys=True,
        )

    if result.healthy:

        lines = [
            "STATUS: OK",
            f"STATE: {result.status}",
        ]

    else:

        lines = [
            "STATUS: FAILED",
            f"STATE: {result.status}",
        ]

    details = result.details

    if details:

        lines.append(
            "DETAILS:"
        )

        for key, value in details.items():

            if isinstance(
                value,
                (dict, list),
            ):

                formatted = json.dumps(
                    value,
                    sort_keys=True,
                )

            else:

                formatted = str(
                    value
                )

            lines.append(
                f"  {key}: {formatted}"
            )

    return "\n".join(
        lines
    )


# ============================================================================
# Main
# ============================================================================

def main(
    argv: list[str] | None = None,
) -> int:

    parser = create_parser()

    try:

        args = parser.parse_args(
            argv
        )

    except SystemExit as exc:

        return int(
            exc.code
            if exc.code is not None
            else EXIT_INVALID
        )

    try:

        result = asyncio.run(
            execute(
                liveness=args.liveness,
                readiness=args.readiness,
            )
        )

    except KeyboardInterrupt:

        return EXIT_UNHEALTHY

    except Exception as exc:

        result = HealthResult.failed(
            status="healthcheck_error",
            details={
                "error": str(exc),
            },
        )

    if not args.quiet:

        print(
            render_result(
                result,
                as_json=args.json,
            )
        )

    return result.exit_code


# ============================================================================
# Script entrypoint
# ============================================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )