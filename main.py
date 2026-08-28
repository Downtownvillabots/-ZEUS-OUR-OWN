DOWNTOWN VILLA
File 9: main.py

Application entry point.

Architecture:
    main.py
        -> core.lifecycle
        -> core.runtime
        -> core.bot
        -> config
        -> future feature modules

This file coordinates startup and shutdown only.
Feature implementations belong in their own modules.
"""

from __future__ import annotations

import asyncio
import signal

from core.lifecycle import get_lifecycle
from core.logging import get_logger
from core.runtime import get_runtime


LOGGER = get_logger(__name__)


async def run() -> None:
    """Run DOWNTOWN VILLA until a shutdown signal is received."""
    runtime = get_runtime()
    lifecycle = get_lifecycle()

    stop_event = asyncio.Event()

    def request_shutdown() -> None:
        if stop_event.is_set():
            return

        LOGGER.info("DOWNTOWN VILLA shutdown requested.")
        stop_event.set()

    loop = asyncio.get_running_loop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except (NotImplementedError, RuntimeError, OSError):
            LOGGER.debug(
                "Signal handler unavailable for %s.",
                signum,
            )

    LOGGER.info(
        "Starting %s version %s.",
        runtime.config.project_name,
        runtime.config.version,
    )

    try:
        await lifecycle.start()
        await stop_event.wait()

    except asyncio.CancelledError:
        LOGGER.info("DOWNTOWN VILLA main task cancelled.")
        raise

    except Exception:
        LOGGER.exception(
            "DOWNTOWN VILLA terminated unexpectedly."
        )
        raise

    finally:
        await lifecycle.stop()


def main() -> None:
    """Synchronous process entry point."""
    try:
        asyncio.run(run())

    except KeyboardInterrupt:
        LOGGER.info(
            "DOWNTOWN VILLA interrupted by keyboard."
        )

    except Exception:
        LOGGER.exception(
            "Fatal DOWNTOWN VILLA process error."
        )
        raise


if __name__ == "__main__":
    main()
