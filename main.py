"""
Production entry point for the bot.

Responsibilities:
    - load configuration
    - configure logging
    - validate startup configuration
    - construct the application
    - select polling/webhook mode
    - handle graceful shutdown
    - return an appropriate process exit code

Run:

    python main.py

or:

    python -m bot

Environment:

    BOT_TOKEN=...
    ENVIRONMENT=production
    LOG_LEVEL=INFO
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

from bot.app.startup import (
    create_application,
    run_application_controlled,
)
from bot.core.config import (
    Settings,
    get_settings,
)
from bot.core.logging import (
    configure_from_environment,
)


logger = logging.getLogger("main")


# ============================================================================
# Constants
# ============================================================================

EXIT_OK = 0

EXIT_CONFIGURATION_ERROR = 2

EXIT_STARTUP_ERROR = 3

EXIT_RUNTIME_ERROR = 4

EXIT_INTERRUPTED = 130


VALID_MODES = {
    "polling",
    "webhook",
}


# ============================================================================
# Environment helpers
# ============================================================================

def get_runtime_mode(
    settings: Settings,
) -> str:
    """
    Resolve the runtime mode.

    Explicit BOT_MODE wins.

    Otherwise webhook mode is selected when WEBHOOK_URL exists.
    """

    configured = os.getenv(
        "BOT_MODE",
        "",
    ).strip().lower()

    if configured:

        if configured not in VALID_MODES:

            raise ValueError(
                "BOT_MODE must be either "
                "'polling' or 'webhook'."
            )

        return configured

    webhook_url = getattr(
        settings.telegram,
        "webhook_url",
        None,
    )

    if webhook_url:

        return "webhook"

    return "polling"


# ============================================================================
# Configuration
# ============================================================================

def load_runtime_settings() -> Settings:
    """
    Load and validate application settings.
    """

    configure_from_environment()

    settings = get_settings()

    # Some existing Settings implementations return a list
    # while others raise directly. Support both patterns.
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

            messages = "\n".join(
                f"- {item}"
                for item in result
            )

        else:

            messages = str(
                result
            )

        raise RuntimeError(
            "Configuration validation failed:\n"
            + messages
        )

    return settings


# ============================================================================
# Logging
# ============================================================================

def log_startup_information(
    settings: Settings,
    mode: str,
) -> None:
    """
    Log safe startup information.

    Secrets are intentionally never logged.
    """

    environment = getattr(
        settings,
        "environment",
        "unknown",
    )

    logger.info(
        "Starting bot."
    )

    logger.info(
        "Environment: %s",
        environment,
    )

    logger.info(
        "Runtime mode: %s",
        mode,
    )

    logger.info(
        "Python version: %s",
        sys.version.split()[0],
    )

    logger.info(
        "Process ID: %s",
        os.getpid(),
    )


# ============================================================================
# Startup
# ============================================================================

async def startup(
    settings: Settings,
    *,
    mode: Optional[str] = None,
) -> None:
    """
    Build and start the complete application.
    """

    application = create_application(
        settings
    )

    runtime_mode = (
        mode
        or get_runtime_mode(
            settings
        )
    )

    if runtime_mode not in VALID_MODES:

        raise ValueError(
            f"Unsupported runtime mode: "
            f"{runtime_mode}"
        )

    log_startup_information(
        settings,
        runtime_mode,
    )

    await run_application_controlled(
        application,
        mode=runtime_mode,
    )


# ============================================================================
# Async main
# ============================================================================

async def async_main(
    *,
    mode: Optional[str] = None,
) -> int:
    """
    Main asynchronous process.

    Returns a process exit code rather than calling sys.exit()
    internally.
    """

    try:

        settings = load_runtime_settings()

    except Exception:

        logger.exception(
            "Unable to load application configuration."
        )

        return EXIT_CONFIGURATION_ERROR

    try:

        await startup(
            settings,
            mode=mode,
        )

    except KeyboardInterrupt:

        logger.info(
            "Application interrupted by operator."
        )

        return EXIT_INTERRUPTED

    except asyncio.CancelledError:

        logger.info(
            "Application task cancelled."
        )

        return EXIT_INTERRUPTED

    except ValueError:

        logger.exception(
            "Invalid runtime configuration."
        )

        return EXIT_CONFIGURATION_ERROR

    except Exception:

        logger.exception(
            "Fatal application runtime error."
        )

        return EXIT_RUNTIME_ERROR

    return EXIT_OK


# ============================================================================
# Synchronous main
# ============================================================================

def main(
    *,
    mode: Optional[str] = None,
) -> int:
    """
    Synchronous process entrypoint.
    """

    try:

        return asyncio.run(
            async_main(
                mode=mode
            )
        )

    except KeyboardInterrupt:

        return EXIT_INTERRUPTED

    except Exception:

        logger.exception(
            "Fatal process-level error."
        )

        return EXIT_RUNTIME_ERROR


# ============================================================================
# CLI
# ============================================================================

def parse_mode_argument(
    argv: list[str],
) -> Optional[str]:
    """
    Parse the intentionally small command-line interface.

    Supported:

        python main.py
        python main.py --polling
        python main.py --webhook
        python main.py --mode polling
        python main.py --mode webhook
    """

    if not argv:
        return None

    mode: Optional[str] = None

    index = 0

    while index < len(argv):

        argument = argv[index]

        if argument in {
            "--polling",
            "polling",
        }:

            mode = "polling"

        elif argument in {
            "--webhook",
            "webhook",
        }:

            mode = "webhook"

        elif argument == "--mode":

            index += 1

            if index >= len(argv):

                raise ValueError(
                    "--mode requires a value."
                )

            mode = (
                argv[index]
                .strip()
                .lower()
            )

        elif argument in {
            "--help",
            "-h",
        }:

            print_help()

            raise SystemExit(
                EXIT_OK
            )

        else:

            raise ValueError(
                f"Unknown argument: {argument}"
            )

        index += 1

    if mode not in VALID_MODES:

        raise ValueError(
            "Runtime mode must be "
            "'polling' or 'webhook'."
        )

    return mode


def print_help() -> None:

    print(
        """
Bot runtime

Usage:
    python main.py
    python main.py --polling
    python main.py --webhook
    python main.py --mode polling
    python main.py --mode webhook

Environment:
    BOT_MODE=polling|webhook
    BOT_TOKEN=<telegram bot token>
    ENVIRONMENT=development|staging|production
    LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
""".strip()
    )


# ============================================================================
# Process entry
# ============================================================================

if __name__ == "__main__":

    try:

        selected_mode = (
            parse_mode_argument(
                sys.argv[1:]
            )
        )

    except SystemExit as exc:

        raise

    except ValueError as exc:

        print(
            f"Error: {exc}",
            file=sys.stderr,
        )

        print(
            file=sys.stderr
        )

        print_help()

        raise SystemExit(
            EXIT_CONFIGURATION_ERROR
        )

    exit_code = main(
        mode=selected_mode
    )

    raise SystemExit(
        exit_code
    )