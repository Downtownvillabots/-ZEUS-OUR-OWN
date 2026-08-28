"""
DOWNTOWN VILLA
File 7: core/runtime.py

Central runtime/application state.

Purpose:
    Keep shared runtime objects in one place without creating global
    variables throughout feature modules.

The runtime will eventually hold:
    - Telegram client
    - validated configuration
    - database manager
    - media manager
    - cache services
    - background task manager
    - other shared application services

For now, only the client and configuration are registered.

Architecture rule:
    Feature modules should receive or retrieve the shared Runtime object
    instead of creating their own competing client/configuration instances.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pyrogram import Client

from config import AppConfig, CONFIG
from core.bot import create_bot_client
from core.logging import get_logger


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class Runtime:
    """
    Shared DOWNTOWN VILLA runtime state.

    This object is intentionally small at the beginning of the project.
    New shared services should be added here only when they are genuinely
    needed by multiple parts of the application.
    """

    config: AppConfig = field(default_factory=lambda: CONFIG)
    client: Client | None = None

    started: bool = False
    stopping: bool = False

    # A central registry for future background tasks.
    # Tasks are created by dedicated services, not randomly throughout
    # feature modules.
    _tasks: set[asyncio.Task[Any]] = field(
        default_factory=set,
        repr=False,
    )

    def initialize_client(self) -> Client:
        """
        Create the shared Telegram client if it does not exist.

        Repeated calls return the same client instance.
        """
        if self.client is None:
            self.client = create_bot_client()
            LOGGER.debug("Shared Telegram client initialized.")

        return self.client

    def register_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        """
        Register a background task with the runtime.

        Registered tasks are automatically removed when they finish.
        """
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def create_task(
        self,
        coroutine: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """
        Create and register a managed background task.

        This gives the project one place to track long-running async work.
        """
        task = asyncio.create_task(
            coroutine,
            name=name,
        )
        return self.register_task(task)

    async def cancel_tasks(self) -> None:
        """Cancel all currently registered background tasks."""
        tasks = list(self._tasks)

        if not tasks:
            return

        LOGGER.info(
            "Stopping %d DOWNTOWN VILLA background task(s).",
            len(tasks),
        )

        for task in tasks:
            if not task.done():
                task.cancel()

        results = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                LOGGER.debug(
                    "Background task stopped with: %s",
                    result,
                )

        self._tasks.clear()

    def mark_started(self) -> None:
        """Mark the application as fully started."""
        self.started = True
        self.stopping = False

        LOGGER.info("DOWNTOWN VILLA runtime marked as started.")

    def mark_stopping(self) -> None:
        """Mark the application as entering shutdown."""
        self.stopping = True
        self.started = False

        LOGGER.info("DOWNTOWN VILLA runtime marked as stopping.")

    async def shutdown(self) -> None:
        """
        Shut down runtime-managed resources.

        The Telegram client's actual stop operation remains owned by the
        application lifecycle in main.py. Runtime only manages shared state
        and background tasks.
        """
        if self.stopping:
            await self.cancel_tasks()
            return

        self.mark_stopping()
        await self.cancel_tasks()

        LOGGER.info("DOWNTOWN VILLA runtime shutdown complete.")


# ---------------------------------------------------------------------------
# Singleton runtime
# ---------------------------------------------------------------------------
#
# There should be one shared runtime for one bot process.
# Keeping construction here makes importing the runtime straightforward:
#
#     from core.runtime import runtime
#
# Future tests can create Runtime(...) directly instead of relying on the
# singleton, which keeps the architecture testable.
#

runtime = Runtime()


def get_runtime() -> Runtime:
    """Return the shared DOWNTOWN VILLA runtime."""
    return runtime


def get_client() -> Client:
    """
    Return the shared Telegram client.

    The client is lazily created so importing this module does not create a
    network connection or Telegram session by itself.
    """
    return runtime.initialize_client()


__all__ = [
    "Runtime",
    "runtime",
    "get_runtime",
    "get_client",
]
