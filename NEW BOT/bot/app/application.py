```python
"""
bot.app.application

High-level Pyrogram application wrapper.

The project uses Pyrogram as its Telegram framework.

Responsibilities:
    - Build the Pyrogram Client exactly once.
    - Attach shared application dependencies to the client.
    - Register the project's handlers exactly once.
    - Initialize and shut down the dependency container.
    - Expose polling/webhook lifecycle helpers.
    - Expose application health information.

Business logic belongs in handlers and services.
Dependency construction belongs in dependencies.py.
Runtime mode selection belongs in startup.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pyrogram import Client

from bot.core.config import Settings
from bot.core.logging import (
    configure_logging,
    set_request_context,
)

from .container import ApplicationContainer


logger = logging.getLogger(
    "bot.app.application"
)


# ============================================================================
# Application
# ============================================================================


class BotApplication:
    """
    Application wrapper around Pyrogram.

    Lifecycle:

        application = BotApplication(...)
        application.build()
        await application.initialize()
        await application.start()
        ...
        await application.shutdown()

    The underlying Pyrogram Client is exposed through ``client``.
    """

    def __init__(
        self,
        settings: Settings,
        container: ApplicationContainer,
        *,
        client: Optional[Client] = None,
    ) -> None:

        if settings is None:
            raise ValueError(
                "settings is required."
            )

        if container is None:
            raise ValueError(
                "container is required."
            )

        self.settings = settings

        self.container = container

        self.client = client

        self._built = (
            client is not None
        )

        self._initialized = False

        self._started = False

        self._stopped = False

        self._handlers_registered = False

        self._shutdown_complete = False

    # ========================================================================
    # Properties
    # ========================================================================

    @property
    def application(
        self,
    ) -> Optional[Client]:
        """
        Backwards-compatible application property.

        The actual Telegram application is a Pyrogram Client.
        """

        return self.client

    @property
    def telegram_application(
        self,
    ) -> Optional[Client]:

        return self.client

    @property
    def built(
        self,
    ) -> bool:

        return self._built

    @property
    def initialized(
        self,
    ) -> bool:

        return self._initialized

    @property
    def started(
        self,
    ) -> bool:

        return self._started

    @property
    def stopped(
        self,
    ) -> bool:

        return self._stopped

    # ========================================================================
    # Settings helpers
    # ========================================================================

    def _telegram_settings(
        self,
    ) -> Any:

        telegram = getattr(
            self.settings,
            "telegram",
            None,
        )

        if telegram is None:

            raise RuntimeError(
                "Telegram settings are not configured."
            )

        return telegram

    def _bot_token(
        self,
    ) -> str:

        telegram = (
            self._telegram_settings()
        )

        token = getattr(
            telegram,
            "bot_token",
            None,
        )

        if not token:

            raise RuntimeError(
                "BOT_TOKEN is not configured."
            )

        return str(
            token
        ).strip()

    def _api_id(
        self,
    ) -> int:

        telegram = (
            self._telegram_settings()
        )

        value = getattr(
            telegram,
            "api_id",
            None,
        )

        if value is None:

            value = getattr(
                self.settings,
                "api_id",
                None,
            )

        if value is None:

            raise RuntimeError(
                "TELEGRAM_API_ID is not configured."
            )

        return int(
            value
        )

    def _api_hash(
        self,
    ) -> str:

        telegram = (
            self._telegram_settings()
        )

        value = getattr(
            telegram,
            "api_hash",
            None,
        )

        if value is None:

            value = getattr(
                self.settings,
                "api_hash",
                None,
            )

        if not value:

            raise RuntimeError(
                "TELEGRAM_API_HASH is not configured."
            )

        return str(
            value
        ).strip()

    def _session_name(
        self,
    ) -> str:

        telegram = (
            self._telegram_settings()
        )

        value = getattr(
            telegram,
            "session_name",
            None,
        )

        return str(
            value
            or "bot"
        )

    def _workdir(
        self,
    ) -> Optional[str]:

        telegram = (
            self._telegram_settings()
        )

        value = getattr(
            telegram,
            "workdir",
            None,
        )

        if value is None:

            return None

        return str(
            value
        )

    # ========================================================================
    # Build
    # ========================================================================

    def build(
        self,
    ) -> Client:
        """
        Build the Pyrogram Client exactly once.

        This does not start the Telegram network connection.
        """

        if self.client is not None:

            return self.client

        configure_logging(
            level=self.settings.log_level
        )

        token = self._bot_token()

        api_id = self._api_id()

        api_hash = self._api_hash()

        session_name = (
            self._session_name()
        )

        workdir = (
            self._workdir()
        )

        client_kwargs: dict[
            str,
            Any,
        ] = {
            "name": session_name,
            "api_id": api_id,
            "api_hash": api_hash,
            "bot_token": token,
            "in_memory": False,
        }

        if workdir:

            client_kwargs[
                "workdir"
            ] = workdir

        self.client = Client(
            **client_kwargs
        )

        self._built = True

        self._attach_dependencies()

        self._register_handlers()

        logger.info(
            "Pyrogram client built."
        )

        return self.client

    # ========================================================================
    # Dependency attachment
    # ========================================================================

    def _attach_dependencies(
        self,
    ) -> None:
        """
        Attach application dependencies to the Pyrogram client.

        Existing handlers in this project expect dependencies such as
        ``client.db``.
        """

        client = self.client

        if client is None:

            raise RuntimeError(
                "Pyrogram client has not been built."
            )

        # --------------------------------------------------------------------
        # Database
        # --------------------------------------------------------------------

        database = getattr(
            self.container,
            "database",
            None,
        )

        if database is not None:

            try:

                setattr(
                    client,
                    "db",
                    database,
                )

            except Exception:

                logger.warning(
                    "Unable to attach database to Pyrogram client.",
                    exc_info=True,
                )

        # --------------------------------------------------------------------
        # Redis
        # --------------------------------------------------------------------

        redis = getattr(
            self.container,
            "redis",
            None,
        )

        if redis is not None:

            try:

                setattr(
                    client,
                    "redis",
                    redis,
                )

            except Exception:

                logger.warning(
                    "Unable to attach Redis to Pyrogram client.",
                    exc_info=True,
                )

        # --------------------------------------------------------------------
        # Cache
        # --------------------------------------------------------------------

        cache = getattr(
            self.container,
            "cache",
            None,
        )

        if cache is not None:

            try:

                setattr(
                    client,
                    "cache",
                    cache,
                )

            except Exception:

                logger.warning(
                    "Unable to attach cache to Pyrogram client.",
                    exc_info=True,
                )

        # --------------------------------------------------------------------
        # Settings
        # --------------------------------------------------------------------

        try:

            setattr(
                client,
                "settings",
                self.settings,
            )

        except Exception:

            logger.warning(
                "Unable to attach settings to Pyrogram client.",
                exc_info=True,
            )

        # --------------------------------------------------------------------
        # Container
        # --------------------------------------------------------------------

        try:

            setattr(
                client,
                "container",
                self.container,
            )

        except Exception:

            logger.warning(
                "Unable to attach dependency container to client.",
                exc_info=True,
            )

    # ========================================================================
    # Handler registration
    # ========================================================================

    def _register_handlers(
        self,
    ) -> None:
        """
        Register all project handlers through bot.handlers.

        The actual handler package uses Pyrogram Client.
        """

        if self._handlers_registered:

            return

        client = self.client

        if client is None:

            raise RuntimeError(
                "Pyrogram client has not been built."
            )

        try:

            from bot.handlers import (
                register_all,
            )

        except ImportError as exc:

            logger.exception(
                "Handler registration API is unavailable."
            )

            raise RuntimeError(
                "bot.handlers.register_all is required."
            ) from exc

        try:

            results = register_all(
                client
            )

        except Exception:

            logger.exception(
                "Pyrogram handler registration failed."
            )

            raise

        failed = [
            name
            for name, success
            in results.items()
            if not success
        ]

        if failed:

            logger.warning(
                "Some handlers failed to register: %s",
                ", ".join(
                    failed
                ),
            )

        self._handlers_registered = True

        logger.info(
            "Pyrogram handlers registered: %d.",
            len(results),
        )

    # ========================================================================
    # Initialization
    # ========================================================================

    async def initialize(
        self,
    ) -> None:
        """
        Initialize the dependency container.

        Pyrogram's ``start()`` owns the Telegram network initialization,
        so we intentionally do not call a python-telegram-bot-style
        ``initialize()`` method here.
        """

        if self._initialized:

            return

        if self._stopped:

            raise RuntimeError(
                "Bot application has already been stopped."
            )

        self.build()

        try:

            if not self.container.ready:

                await self.container.initialize()

        except Exception:

            logger.exception(
                "Dependency container initialization failed."
            )

            raise

        self._attach_dependencies()

        self._initialized = True

        self._shutdown_complete = False

        logger.info(
            "Bot application initialized."
        )

    # ========================================================================
    # Start
    # ========================================================================

    async def start(
        self,
    ) -> Client:
        """
        Start the Pyrogram client.

        Pyrogram's ``start()`` establishes the Telegram connection.
        """

        if self._started:

            if self.client is None:

                raise RuntimeError(
                    "Pyrogram client is unavailable."
                )

            return self.client

        if not self._initialized:

            await self.initialize()

        client = self.client

        if client is None:

            raise RuntimeError(
                "Pyrogram client is unavailable."
            )

        try:

            await client.start()

        except Exception:

            logger.exception(
                "Pyrogram client startup failed."
            )

            raise

        self._started = True

        self._stopped = False

        logger.info(
            "Pyrogram client started."
        )

        return client

    # ========================================================================
    # Stop
    # ========================================================================

    async def stop(
        self,
    ) -> None:
        """
        Stop the Pyrogram client.

        Dependencies remain available until ``shutdown()`` is called.
        """

        client = self.client

        if client is None:

            self._started = False

            return

        if not self._started:

            return

        try:

            await client.stop()

        except Exception:

            logger.exception(
                "Pyrogram client stop failed."
            )

            raise

        finally:

            self._started = False

        logger.info(
            "Pyrogram client stopped."
        )

    # ========================================================================
    # Shutdown
    # ========================================================================

    async def shutdown(
        self,
    ) -> None:
        """
        Fully shut down Telegram and application dependencies.

        Shutdown is idempotent.
        """

        if self._shutdown_complete:

            return

        errors: list[
            BaseException
        ] = []

        # --------------------------------------------------------------------
        # Pyrogram
        # --------------------------------------------------------------------

        if self.client is not None:

            try:

                if self._started:

                    await self.client.stop()

            except BaseException as exc:

                errors.append(
                    exc
                )

                logger.exception(
                    "Pyrogram client shutdown failed."
                )

            finally:

                self._started = False

        # --------------------------------------------------------------------
        # Dependency container
        # --------------------------------------------------------------------

        try:

            await self.container.shutdown()

        except BaseException as exc:

            errors.append(
                exc
            )

            logger.exception(
                "Application container shutdown failed."
            )

        self._initialized = False

        self._stopped = True

        self._shutdown_complete = True

        if errors:

            raise RuntimeError(
                "Application shutdown completed with "
                f"{len(errors)} error(s)."
            ) from errors[0]

        logger.info(
            "Bot application shutdown completed."
        )

    # ========================================================================
    # Polling
    # ========================================================================

    async def run_polling(
        self,
    ) -> None:
        """
        Start the Pyrogram client and keep it alive.

        This is a convenience method. The normal process-level lifecycle
        remains owned by startup.py.
        """

        try:

            await self.start()

            logger.info(
                "Bot polling started."
            )

            await asyncio.Event().wait()

        finally:

            await self.shutdown()

    # ========================================================================
    # Webhook
    # ========================================================================

    async def run_webhook(
        self,
    ) -> None:
        """
        Start the Pyrogram client for webhook-capable deployments.

        Pyrogram normally operates through its client update loop rather
        than python-telegram-bot's updater API. Webhook support therefore
        depends on the project's existing Pyrogram/network configuration.

        We start the client here and keep the process alive.
        """

        try:

            await self.start()

            logger.info(
                "Bot webhook/runtime mode started."
            )

            await asyncio.Event().wait()

        finally:

            await self.shutdown()

    # ========================================================================
    # Health
    # ========================================================================

    def health(
        self,
    ) -> dict[str, Any]:
        """
        Return a safe application health snapshot.

        No credentials or secrets are included.
        """

        container_ready = bool(
            self.container.ready
        )

        client_ready = bool(
            self._started
        )

        return {
            "status": (
                "ok"
                if (
                    container_ready
                    and client_ready
                )
                else "starting"
            ),
            "environment": (
                self.settings.environment
            ),
            "container": (
                self.container.summary()
            ),
            "telegram_framework": (
                "pyrogram"
            ),
            "telegram_built": (
                self._built
            ),
            "telegram_initialized": (
                self._initialized
            ),
            "telegram_started": (
                self._started
            ),
            "handlers_registered": (
                self._handlers_registered
            ),
        }

    # ========================================================================
    # Context helper
    # ========================================================================

    @staticmethod
    def set_update_context(
        update: Any,
        request_id: Optional[str] = None,
    ) -> None:
        """
        Populate structured logging context from a Pyrogram message/update.

        Pyrogram Message objects expose ``from_user`` and ``chat``.
        """

        if update is None:

            return

        user = getattr(
            update,
            "from_user",
            None,
        )

        chat = getattr(
            update,
            "chat",
            None,
        )

        user_id = getattr(
            user,
            "id",
            None,
        )

        chat_id = getattr(
            chat,
            "id",
            None,
        )

        set_request_context(
            request_id=request_id,
            user_id=user_id,
            chat_id=chat_id,
        )


# ============================================================================
# Public exports
# ============================================================================


__all__ = [
    "BotApplication",
]
```
