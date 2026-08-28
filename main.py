from __future__ import annotations

import asyncio
import signal

from app.config import get_config
from app.logging import get_logger
from app.runtime import create_runtime
from app.web import start_health_server
from functions.loader import load_functions


LOGGER = get_logger(__name__)


async def run() -> None:
    config = get_config()
    runtime = create_runtime(config)

    stop_event = asyncio.Event()

    def request_shutdown() -> None:
        if not stop_event.is_set():
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

    load_functions(runtime)

    try:
        await start_health_server(runtime)
        await runtime.start()

        LOGGER.info("DOWNTOWN VILLA is ONLINE.")

        await stop_event.wait()

    except asyncio.CancelledError:
        LOGGER.info("DOWNTOWN VILLA main task cancelled.")
        raise

    except Exception:
        LOGGER.exception(
            "DOWNTOWN VILLA stopped because of an error."
        )
        raise

    finally:
        await runtime.stop()


def main() -> None:
    try:
        asyncio.run(run())

    except KeyboardInterrupt:
        LOGGER.info(
            "DOWNTOWN VILLA stopped by keyboard."
        )

    except Exception:
        LOGGER.exception(
            "Fatal DOWNTOWN VILLA process error."
        )
        raise


if __name__ == "__main__":
    main()
