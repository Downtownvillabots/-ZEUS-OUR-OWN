"""
DOWNTOWN VILLA
File 8: core/lifecycle.py

Application lifecycle manager.

Responsibilities:
    - Start the shared Telegram client.
    - Stop the client cleanly.
    - Track runtime state.
    - Provide one reusable lifecycle implementation for main.py.
    - Keep startup/shutdown orchestration out of feature modules.

Feature modules must not start or stop the Telegram client themselves.

The lifecycle is intentionally independent of:
    - search
    - database
    - media indexing
    - admin features
    - backup
    - user-facing commands

Those systems will be attached through dedicated modules later.
"""

from __future__ import annotations

import asyncio
from typing import Final

from pyrogram import Client

from core.errors import report_error
from core.logging import get_logger
from core.runtime import Runtime, get_runtime


LOGGER = get_logger(__name__)

START_TIMEOUT_SECONDS: Final[float] = 60.0
STOP_TIMEOUT_SECONDS: Final[float] = 30.0


class BotLifecycle:
    """
    Controls the Telegram application's startup and shutdown sequence.

    A lifecycle object receives a Runtime instead of creating its own
    Telegram client. This prevents duplicate clients and keeps the
    application architecture predictable.
    """

    def __init__(
        self,
        runtime: Runtime | None = None,
    ) -> None:
        self.runtime = runtime or get_runtime()

    @property
    def client(self) -> Client:
        """Return the shared Telegram client."""
        return self.runtime.initialize_client()

    async def start(self) -> Client:
        """
        Start the DOWNTOWN VILLA Telegram client.

        Returns:
            The already-initialized shared Pyrogram client.
        """
        if self.runtime.started:
            LOGGER.debug("DOWNTOWN VILLA is already running.")
            return self.client

        if self.runtime.stopping:
            raise RuntimeError(
                "DOWNTOWN VILLA is currently shutting down."
            )

        client = self.client

        LOGGER.info("Starting DOWNTOWN VILLA Telegram client...")

        try:
            await asyncio.wait_for(
                client.start(),
                timeout=START_TIMEOUT_SECONDS,
            )

            self.runtime.mark_started()

            me = await client.get_me()

            username = (
                f"@{me.username}"
                if getattr(me, "username", None)
                else "no username"
            )

            LOGGER.info(
                "DOWNTOWN VILLA is ONLINE | id=%s | username=%s",
                getattr(me, "id", "unknown"),
                username,
            )

            return client

        except asyncio.TimeoutError as exc:
            LOGGER.error(
                "DOWNTOWN VILLA startup timed out after %.1f seconds.",
                START_TIMEOUT_SECONDS,
            )
            report_error(
                exc,
                context="Telegram client startup timeout",
            )

            await self._safe_stop_client()
            raise RuntimeError(
                "DOWNTOWN VILLA Telegram client startup timed out."
            ) from exc

        except Exception as exc:
            report_error(
                exc,
                context="DOWNTOWN VILLA Telegram client startup",
            )

            await self._safe_stop_client()
            raise

    async def stop(self) -> None:
        """
        Stop the Telegram client and runtime-managed background tasks.

        The method is safe to call repeatedly.
        """
        if self.runtime.stopping:
            LOGGER.debug("DOWNTOWN VILLA shutdown already in progress.")
            return

        if not self.runtime.started and self.runtime.client is None:
            LOGGER.debug("DOWNTOWN VILLA is not running.")
            return

        LOGGER.info("Stopping DOWNTOWN VILLA...")

        self.runtime.mark_stopping()

        await self.runtime.cancel_tasks()

        await self._safe_stop_client()

        LOGGER.info("DOWNTOWN VILLA is OFFLINE.")

    async def _safe_stop_client(self) -> None:
        """Stop the shared Telegram client without hiding shutdown errors."""
        client = self.runtime.client

        if client is None:
            return

        try:
            await asyncio.wait_for(
                client.stop(),
                timeout=STOP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            LOGGER.error(
                "Telegram client shutdown timed out after %.1f seconds.",
                STOP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            report_error(
                exc,
                context="DOWNTOWN VILLA Telegram client shutdown",
            )
        finally:
            self.runtime.client = None
            self.runtime.started = False

    async def run_until_stopped(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        """
        Start the bot and wait until the supplied stop event is triggered.

        This is useful for the process entry point and hosting environments.
        """
        await self.start()

        try:
            await stop_event.wait()
        finally:
            await self.stop()


# ---------------------------------------------------------------------------
# Shared lifecycle
# ---------------------------------------------------------------------------

lifecycle = BotLifecycle()


def get_lifecycle() -> BotLifecycle:
    """Return the shared DOWNTOWN VILLA lifecycle manager."""
    return lifecycle


__all__ = [
    "START_TIMEOUT_SECONDS",
    "STOP_TIMEOUT_SECONDS",
    "BotLifecycle",
    "lifecycle",
    "get_lifecycle",
]
