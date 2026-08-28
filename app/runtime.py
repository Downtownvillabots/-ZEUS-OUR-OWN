"""
DOWNTOWN VILLA
Shared application runtime.

Only shared resources belong here. Feature-specific state stays inside
its feature module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pyrogram import Client

from app.config import Config
from app.logging import get_logger


LOGGER = get_logger(__name__)


@dataclass(slots=True)
class Runtime:
    config: Config
    client: Client
    tasks: set[asyncio.Task] = field(default_factory=set)
    started: bool = False
    web_runner: object | None = None

    def add_task(self, task: asyncio.Task) -> asyncio.Task:
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def start(self) -> None:
        if self.started:
            return

        await self.client.start()
        self.started = True

        me = await self.client.get_me()
        LOGGER.info(
            "Connected as @%s (id=%s).",
            me.username or "no_username",
            me.id,
        )

    async def stop(self) -> None:
        if self.web_runner is not None:
            cleanup = getattr(self.web_runner, "cleanup", None)
            if cleanup is not None:
                await cleanup()
            self.web_runner = None

        for task in list(self.tasks):
            if not task.done():
                task.cancel()

        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks.clear()

        if self.started:
            await self.client.stop()
            self.started = False

        LOGGER.info("DOWNTOWN VILLA shutdown complete.")


def create_runtime(config: Config) -> Runtime:
    client = Client(
        name=config.session_name,
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workdir="/app",
    )

    return Runtime(
        config=config,
        client=client,
    )
