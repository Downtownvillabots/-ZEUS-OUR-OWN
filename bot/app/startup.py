
"""
bot.app.startup

Public application startup and shutdown entry points.

The project uses Pyrogram.

Responsibilities:
    - Load and validate Settings.
    - Build the dependency container.
    - Create BotApplication.
    - Start the Pyrogram client.
    - Handle shutdown signals.
    - Perform graceful cleanup.

Business logic remains in handlers/services.
Dependency construction remains in dependencies.py.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from bot.core.config import (
    Settings,
    get_settings,
    load_settings,
)
from bot.core.logging import (
    configure_from_environment,
)

from .application import BotApplication
from .container import ApplicationContainer
from .dependencies import build_container


logger = logging.getLogger(
    "bot.app.startup"
)


# ============================================================================
# Constants
# ============================================================================

VALID_MODES = frozenset(
    {
        "polling",
        "webhook",
    }
)


# ============================================================================
# Mode resolution
# ============================================================================


def resolve_mode(
    settings: Settings,
    mode: Optional[str] = None,
) -> str:
    """
    Resolve the runtime mode.

    Pyrogram primarily uses its normal client update loop. The mode value
    is retained for compatibility with the deployment configuration.

    Explicit mode takes precedence over configuration.
    """

    if mode is not None:

        selected = (
            str(mode)
            .strip()
            .lower()
        )

    else:

        telegram = getattr(
            settings,
            "telegram",
            None,
        )

        webhook_url = getattr(
            telegram,
            "webhook_url",
            None,
        )

        selected = (
            "webhook"
            if webhook_url
            else "polling"
        )

    if selected not in VALID_MODES:

        raise ValueError(
            "mode must be either "
            "'polling' or 'webhook'."
        )

    return selected


# ============================================================================
# Application factory
# ============================================================================


def create_application(
    settings: Optional[Settings] = None,
    *,
    container: Optional[
        ApplicationContainer
    ] = None,
) -> BotApplication:
    """
    Create the application without starting Telegram.
    """

    configure_from_environment()

    resolved_settings = (
        settings
        if settings is not None
        else get_settings()
    )

    resolved_settings.validate()

    resolved_container = (
        container
        if container is not None
        else build_container(
            resolved_settings
        )
    )

    application = BotApplication(
        resolved_settings,
        resolved_container,
    )

    return application


# ============================================================================
# Shutdown controller
# ============================================================================


class ShutdownController:
    """
    Converts process signals into an asyncio shutdown event.
    """

    def __init__(self) -> None:

        self.event = asyncio.Event()

        self._installed = False

    @property
    def installed(
        self,
    ) -> bool:

        return self._installed

    def install(
        self,
    ) -> None:

        if self._installed:
            return

        try:

            loop = (
                asyncio.get_running_loop()
            )

        except RuntimeError:

            logger.warning(
                "Cannot install shutdown signals "
                "without a running event loop."
            )

            return

        for signal_name in (
            "SIGINT",
            "SIGTERM",
        ):

            signal_value = getattr(
                signal,
                signal_name,
                None,
            )

            if signal_value is None:
                continue

            try:

                loop.add_signal_handler(
                    signal_value,
                    self.request_shutdown,
                )

            except (
                NotImplementedError,
                RuntimeError,
            ):

                logger.debug(
                    "Signal handler unavailable for %s.",
                    signal_name,
                )

        self._installed = True

    def request_shutdown(
        self,
    ) -> None:

        if self.event.is_set():
            return

        logger.info(
            "Shutdown signal received."
        )

        self.event.set()

    async def wait(
        self,
    ) -> None:

        await self.event.wait()


# ============================================================================
# Controlled application runner
# ============================================================================


async def run_application_controlled(
    application: BotApplication,
    *,
    mode: Optional[str] = None,
) -> None:
    """
    Start the BotApplication and keep it alive until shutdown.

    Unlike the previous implementation, this function does not use
    python-telegram-bot's Application/updater APIs.
    """

    if application is None:

        raise ValueError(
            "application is required."
        )

    controller = ShutdownController()

    controller.install()

    selected_mode = resolve_mode(
        application.settings,
        mode,
    )

    logger.info(
        "Starting Pyrogram application in %s mode.",
        selected_mode,
    )

    try:

        await application.start()

        logger.info(
            "Pyrogram application is running."
        )

        # Pyrogram owns the Telegram update loop.
        #
        # We simply keep the application process alive until:
        #
        #   SIGINT
        #   SIGTERM
        #
        # or task cancellation.

        await controller.wait()

    except asyncio.CancelledError:

        logger.info(
            "Application runner cancelled."
        )

        raise

    except Exception:

        logger.exception(
            "Application runtime failed."
        )

        raise

    finally:

        try:

            await application.shutdown()

        except Exception:

            logger.exception(
                "Application shutdown failed."
            )

            raise


# ============================================================================
# Async public runner
# ============================================================================


async def run_application_async(
    application: Optional[
        BotApplication
    ] = None,
    *,
    mode: Optional[str] = None,
) -> None:
    """
    Asynchronous public entry point.
    """

    resolved_application = (
        application
        if application is not None
        else create_application()
    )

    await run_application_controlled(
        resolved_application,
        mode=mode,
    )


# ============================================================================
# Synchronous public runner
# ============================================================================


def run_application(
    application: Optional[
        BotApplication
    ] = None,
    *,
    mode: Optional[str] = None,
) -> None:
    """
    Synchronous entry point for run.py and deployment commands.
    """

    resolved_application = (
        application
        if application is not None
        else create_application()
    )

    try:

        asyncio.run(
            run_application_controlled(
                resolved_application,
                mode=mode,
            )
        )

    except KeyboardInterrupt:

        logger.info(
            "Application interrupted by keyboard."
        )


# ============================================================================
# Startup configuration validation
# ============================================================================


def validate_startup_configuration() -> Settings:
    """
    Reload and validate the deployment configuration.
    """

    settings = load_settings(
        force_reload=True
    )

    settings.validate()

    return settings


# ============================================================================
# Startup diagnostics
# ============================================================================


def startup_summary(
    application: BotApplication,
) -> dict[str, object]:
    """
    Return a safe startup summary.

    Secrets are intentionally excluded.
    """

    mode = resolve_mode(
        application.settings
    )

    return {
        "framework": "pyrogram",
        "mode": mode,
        "built": application.built,
        "initialized": application.initialized,
        "started": application.started,
        "stopped": application.stopped,
        "handlers_registered": (
            getattr(
                application,
                "_handlers_registered",
                False,
            )
        ),
    }


# ============================================================================
# Public exports
# ============================================================================


__all__ = [
    "VALID_MODES",
    "ShutdownController",
    "resolve_mode",
    "create_application",
    "run_application_controlled",
    "run_application_async",
    "run_application",
    "validate_startup_configuration",
    "startup_summary",
]

