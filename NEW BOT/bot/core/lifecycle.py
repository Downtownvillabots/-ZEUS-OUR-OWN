"""
bot.core.lifecycle

Application lifecycle orchestration.

This module keeps startup/shutdown concerns in one place.

The lifecycle manager can:
    - Validate configuration.
    - Initialize logging.
    - Initialize database.
    - Initialize Redis.
    - Start external resources.
    - Register cleanup callbacks.
    - Shut everything down in reverse order.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Optional

from .config import Settings
from .logging import (
    configure_logging,
    clear_request_context,
)


logger = logging.getLogger(
    "bot.core.lifecycle"
)


LifecycleCallback = Callable[
    [],
    Any,
]


@dataclass(slots=True)
class LifecycleState:

    started: bool = False

    stopping: bool = False

    stopped: bool = False

    database_ready: bool = False

    redis_ready: bool = False

    bot_ready: bool = False


class LifecycleManager:

    def __init__(
        self,
        settings: Settings,
        *,
        database: Any = None,
        redis: Any = None,
        bot: Any = None,
    ) -> None:

        self.settings = settings

        self.database = database

        self.redis = redis

        self.bot = bot

        self.state = (
            LifecycleState()
        )

        self._startup_callbacks: list[
            LifecycleCallback
        ] = []

        self._shutdown_callbacks: list[
            LifecycleCallback
        ] = []

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_startup(
        self,
        callback: LifecycleCallback,
    ) -> LifecycleCallback:

        self._startup_callbacks.append(
            callback
        )

        return callback

    def on_shutdown(
        self,
        callback: LifecycleCallback,
    ) -> LifecycleCallback:

        self._shutdown_callbacks.append(
            callback
        )

        return callback

    # ------------------------------------------------------------------
    # Generic invocation
    # ------------------------------------------------------------------

    @staticmethod
    async def _invoke(
        callback: LifecycleCallback,
    ) -> Any:

        result = callback()

        if hasattr(
            result,
            "__await__",
        ):

            return await result

        return result

    # ------------------------------------------------------------------
    # Resource initialization
    # ------------------------------------------------------------------

    async def initialize_database(
        self,
    ) -> None:

        if self.database is None:
            return

        for method_name in (
            "connect",
            "initialize",
            "start",
        ):

            method = getattr(
                self.database,
                method_name,
                None,
            )

            if method is None:
                continue

            await self._invoke(
                method
            )

            self.state.database_ready = True

            logger.info(
                "Database initialized."
            )

            return

    async def initialize_redis(
        self,
    ) -> None:

        if (
            self.redis is None
            or not self.settings.redis.enabled
        ):
            return

        for method_name in (
            "connect",
            "initialize",
            "start",
        ):

            method = getattr(
                self.redis,
                method_name,
                None,
            )

            if method is None:
                continue

            await self._invoke(
                method
            )

            self.state.redis_ready = True

            logger.info(
                "Redis initialized."
            )

            return

    async def initialize_bot(
        self,
    ) -> None:

        if self.bot is None:
            return

        for method_name in (
            "initialize",
            "initialize_application",
            "start",
        ):

            method = getattr(
                self.bot,
                method_name,
                None,
            )

            if method is None:
                continue

            await self._invoke(
                method
            )

            self.state.bot_ready = True

            logger.info(
                "Bot initialized."
            )

            return

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def startup(
        self,
    ) -> None:

        async with self._lock:

            if self.state.started:
                return

            if self.state.stopping:
                raise RuntimeError(
                    "Application is stopping."
                )

            logger.info(
                "Application startup beginning."
            )

            # Validate before touching external resources.
            self.settings.validate()

            configure_logging(
                level=self.settings.log_level
            )

            clear_request_context()

            try:

                await self.initialize_database()

                await self.initialize_redis()

                await self.initialize_bot()

                for callback in (
                    self._startup_callbacks
                ):

                    await self._invoke(
                        callback
                    )

                self.state.started = True

                self.state.stopped = False

                logger.info(
                    "Application startup completed."
                )

            except Exception:

                logger.exception(
                    "Application startup failed."
                )

                await self._shutdown_internal()

                raise

    # ------------------------------------------------------------------
    # Shutdown resources
    # ------------------------------------------------------------------

    async def shutdown_database(
        self,
    ) -> None:

        if (
            self.database is None
            or not self.state.database_ready
        ):
            return

        for method_name in (
            "disconnect",
            "close",
            "shutdown",
            "stop",
        ):

            method = getattr(
                self.database,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                await self._invoke(
                    method
                )

            finally:

                self.state.database_ready = False

            logger.info(
                "Database shut down."
            )

            return

    async def shutdown_redis(
        self,
    ) -> None:

        if (
            self.redis is None
            or not self.state.redis_ready
        ):
            return

        for method_name in (
            "disconnect",
            "close",
            "shutdown",
            "stop",
        ):

            method = getattr(
                self.redis,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                await self._invoke(
                    method
                )

            finally:

                self.state.redis_ready = False

            logger.info(
                "Redis shut down."
            )

            return

    async def shutdown_bot(
        self,
    ) -> None:

        if (
            self.bot is None
            or not self.state.bot_ready
        ):
            return

        for method_name in (
            "shutdown",
            "stop",
            "close",
        ):

            method = getattr(
                self.bot,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                await self._invoke(
                    method
                )

            finally:

                self.state.bot_ready = False

            logger.info(
                "Bot shut down."
            )

            return

    # ------------------------------------------------------------------
    # Internal shutdown
    # ------------------------------------------------------------------

    async def _shutdown_internal(
        self,
    ) -> None:

        errors: list[BaseException] = []

        # Custom callbacks first.
        for callback in reversed(
            self._shutdown_callbacks
        ):

            try:

                await self._invoke(
                    callback
                )

            except BaseException as exc:

                errors.append(
                    exc
                )

                logger.exception(
                    "Shutdown callback failed."
                )

        # Stop bot before infrastructure.
        try:

            await self.shutdown_bot()

        except BaseException as exc:

            errors.append(
                exc
            )

            logger.exception(
                "Bot shutdown failed."
            )

        try:

            await self.shutdown_redis()

        except BaseException as exc:

            errors.append(
                exc
            )

            logger.exception(
                "Redis shutdown failed."
            )

        try:

            await self.shutdown_database()

        except BaseException as exc:

            errors.append(
                exc
            )

            logger.exception(
                "Database shutdown failed."
            )

        self.state.started = False

        self.state.stopped = True

        if errors:

            logger.error(
                "Shutdown completed with %d error(s).",
                len(errors),
            )

    # ------------------------------------------------------------------
    # Public shutdown
    # ------------------------------------------------------------------

    async def shutdown(
        self,
    ) -> None:

        async with self._lock:

            if self.state.stopped:
                return

            self.state.stopping = True

            logger.info(
                "Application shutdown beginning."
            )

            try:

                await self._shutdown_internal()

            finally:

                self.state.stopping = False

                clear_request_context()

            logger.info(
                "Application shutdown completed."
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(
        self,
    ) -> "LifecycleManager":

        await self.startup()

        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:

        await self.shutdown()

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    @property
    def is_running(
        self,
    ) -> bool:

        return (
            self.state.started
            and not self.state.stopping
            and not self.state.stopped
        )

    @property
    def is_ready(
        self,
    ) -> bool:

        if not self.state.started:
            return False

        if (
            self.database is not None
            and not self.state.database_ready
        ):
            return False

        if (
            self.redis is not None
            and self.settings.redis.enabled
            and not self.state.redis_ready
        ):
            return False

        return True


# ============================================================================
# Application runner
# ============================================================================

async def run_lifecycle(
    lifecycle: LifecycleManager,
    main: Callable[[], Awaitable[Any]],
) -> Any:

    await lifecycle.startup()

    try:

        return await main()

    finally:

        await lifecycle.shutdown()


def create_lifecycle(
    settings: Settings,
    *,
    database: Any = None,
    redis: Any = None,
    bot: Any = None,
) -> LifecycleManager:

    return LifecycleManager(
        settings,
        database=database,
        redis=redis,
        bot=bot,
    )


__all__ = [
    "LifecycleState",
    "LifecycleManager",
    "run_lifecycle",
    "create_lifecycle",
]