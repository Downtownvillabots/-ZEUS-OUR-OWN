"""
run.py

Production-friendly launcher for the bot.

Examples:

    python run.py
    python run.py --polling
    python run.py --webhook
    python run.py --mode polling

Environment:

    BOT_MODE=polling
    BOT_TOKEN=...

The launcher does not contain Telegram business logic.
It delegates application construction and lifecycle handling
to the bot application layer.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


# ============================================================================
# Runtime configuration
# ============================================================================

VALID_MODES = {
    "polling",
    "webhook",
}


def resolve_mode(
    explicit_mode: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve the requested runtime mode.

    Priority:

        1. Explicit command-line mode
        2. BOT_MODE environment variable
        3. None -> application decides
    """

    if explicit_mode:

        mode = explicit_mode.strip().lower()

        if mode not in VALID_MODES:

            raise ValueError(
                "Mode must be 'polling' or 'webhook'."
            )

        return mode

    environment_mode = os.getenv(
        "BOT_MODE",
        "",
    ).strip().lower()

    if environment_mode:

        if environment_mode not in VALID_MODES:

            raise ValueError(
                "BOT_MODE must be 'polling' or 'webhook'."
            )

        return environment_mode

    return None


# ============================================================================
# CLI
# ============================================================================

def print_help() -> None:
    print(
        """
Bot launcher

Usage:
    python run.py
    python run.py --polling
    python run.py --webhook
    python run.py --mode polling
    python run.py --mode webhook

Options:
    --polling       Run using Telegram polling.
    --webhook       Run using Telegram webhook.
    --mode MODE     Explicitly select polling or webhook.
    --help          Show this help message.

Environment:
    BOT_MODE        polling or webhook
    BOT_TOKEN       Telegram bot token
""".strip()
    )


def parse_args(
    argv: list[str],
) -> Optional[str]:
    """
    Parse launcher arguments.

    The parser deliberately remains dependency-free so that the
    launcher can execute before the rest of the application is
    fully initialized.
    """

    if not argv:
        return None

    mode: Optional[str] = None

    index = 0

    while index < len(argv):

        argument = argv[index].strip()

        if argument in {
            "--help",
            "-h",
        }:

            print_help()

            raise SystemExit(0)

        if argument == "--polling":

            if mode is not None:

                raise ValueError(
                    "Multiple runtime modes were supplied."
                )

            mode = "polling"

            index += 1

            continue

        if argument == "--webhook":

            if mode is not None:

                raise ValueError(
                    "Multiple runtime modes were supplied."
                )

            mode = "webhook"

            index += 1

            continue

        if argument == "--mode":

            if mode is not None:

                raise ValueError(
                    "Multiple runtime modes were supplied."
                )

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

            if mode not in VALID_MODES:

                raise ValueError(
                    "Mode must be 'polling' or 'webhook'."
                )

            index += 1

            continue

        if argument.startswith(
            "--mode="
        ):

            if mode is not None:

                raise ValueError(
                    "Multiple runtime modes were supplied."
                )

            mode = (
                argument.split(
                    "=",
                    1,
                )[1]
                .strip()
                .lower()
            )

            if mode not in VALID_MODES:

                raise ValueError(
                    "Mode must be 'polling' or 'webhook'."
                )

            index += 1

            continue

        raise ValueError(
            f"Unknown argument: {argument}"
        )

    return mode


# ============================================================================
# Environment validation
# ============================================================================

def validate_environment() -> None:
    """
    Perform minimal launcher-level validation.

    Full validation is performed by bot.core.config during application
    startup. This function only catches obvious deployment mistakes.
    """

    token = os.getenv(
        "BOT_TOKEN",
        "",
    ).strip()

    # Do not print the token.
    if not token:

        raise RuntimeError(
            "BOT_TOKEN environment variable is not configured."
        )


# ============================================================================
# Application execution
# ============================================================================

def execute(
    mode: Optional[str] = None,
) -> int:
    """
    Execute the application.

    Imports are intentionally delayed until after argument parsing.
    This keeps --help lightweight and avoids initializing application
    dependencies unnecessarily.
    """

    validate_environment()

    from bot.app.startup import (
        run_application,
    )

    run_application(
        mode=mode
    )

    return 0


# ============================================================================
# Main
# ============================================================================

def main(
    argv: Optional[
        list[str]
    ] = None,
) -> int:

    arguments = (
        list(sys.argv[1:])
        if argv is None
        else list(argv)
    )

    try:

        cli_mode = parse_args(
            arguments
        )

        mode = resolve_mode(
            cli_mode
        )

    except SystemExit:

        raise

    except ValueError as exc:

        print(
            f"Configuration error: {exc}",
            file=sys.stderr,
        )

        print(
            file=sys.stderr
        )

        print_help()

        return 2

    except RuntimeError as exc:

        print(
            f"Environment error: {exc}",
            file=sys.stderr,
        )

        return 2

    try:

        return execute(
            mode=mode
        )

    except KeyboardInterrupt:

        print(
            "Bot stopped."
        )

        return 130

    except Exception as exc:

        print(
            f"Bot startup failed: {exc}",
            file=sys.stderr,
        )

        return 1


# ============================================================================
# Script entrypoint
# ============================================================================

if __name__ == "__main__":

    raise SystemExit(
        main()
    )