"""
bot.middleware.logging

Request/update logging middleware.

Logs useful operational information without dumping sensitive
Telegram payloads or message contents into logs.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from telegram import Update
from telegram.ext import ContextTypes


logger = logging.getLogger("bot.middleware")


class LoggingMiddleware:
    """
    Lightweight request logger.

    Stores a request ID in context.user_data so downstream services
    can include it in their own logs.
    """

    def __init__(
        self,
        *,
        logger_instance: Optional[
            logging.Logger
        ] = None,
        log_callbacks: bool = True,
        log_commands: bool = True,
        log_messages: bool = False,
    ) -> None:

        self.logger = (
            logger_instance
            or logger
        )

        self.log_callbacks = (
            bool(log_callbacks)
        )

        self.log_commands = (
            bool(log_commands)
        )

        self.log_messages = (
            bool(log_messages)
        )

    # ------------------------------------------------------------------
    # Request ID
    # ------------------------------------------------------------------

    @staticmethod
    def create_request_id() -> str:

        return uuid.uuid4().hex[:12]

    # ------------------------------------------------------------------
    # Update type
    # ------------------------------------------------------------------

    @staticmethod
    def get_update_type(
        update: Update,
    ) -> str:

        if update.callback_query is not None:
            return "callback"

        if update.message is not None:

            if update.message.text:

                text = update.message.text

                if text.startswith("/"):
                    return "command"

                return "message"

            if update.message.document is not None:
                return "document"

            if update.message.video is not None:
                return "video"

            if update.message.audio is not None:
                return "audio"

            if update.message.photo:
                return "photo"

            return "message"

        if update.inline_query is not None:
            return "inline_query"

        if update.chat_member is not None:
            return "chat_member"

        if update.my_chat_member is not None:
            return "my_chat_member"

        return "unknown"

    # ------------------------------------------------------------------
    # Command
    # ------------------------------------------------------------------

    @staticmethod
    def get_command(
        update: Update,
    ) -> Optional[str]:

        message = update.message

        if message is None:
            return None

        text = message.text

        if not text:
            return None

        if not text.startswith("/"):
            return None

        return text.split(
            maxsplit=1
        )[0]

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------

    @staticmethod
    def get_callback(
        update: Update,
    ) -> Optional[str]:

        callback = update.callback_query

        if callback is None:
            return None

        return callback.data

    # ------------------------------------------------------------------
    # User ID
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_id(
        update: Update,
    ) -> Optional[int]:

        user = update.effective_user

        if user is None:
            return None

        return int(user.id)

    # ------------------------------------------------------------------
    # Chat ID
    # ------------------------------------------------------------------

    @staticmethod
    def get_chat_id(
        update: Update,
    ) -> Optional[int]:

        chat = update.effective_chat

        if chat is None:
            return None

        return int(chat.id)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_start(
        self,
        update: Update,
        request_id: str,
    ) -> None:

        update_type = (
            self.get_update_type(update)
        )

        user_id = self.get_user_id(
            update
        )

        chat_id = self.get_chat_id(
            update
        )

        extra: dict[str, Any] = {
            "request_id": request_id,
            "update_type": update_type,
            "user_id": user_id,
            "chat_id": chat_id,
        }

        if (
            update_type == "callback"
            and self.log_callbacks
        ):

            extra["callback"] = (
                self.get_callback(update)
            )

        if (
            update_type == "command"
            and self.log_commands
        ):

            extra["command"] = (
                self.get_command(update)
            )

        if (
            update_type == "message"
            and self.log_messages
        ):

            message = update.message

            if message is not None:

                # Deliberately do not log full message text
                # by default because it may contain private data.
                extra["message_length"] = len(
                    message.text or ""
                )

        self.logger.info(
            "Update received: %s",
            extra,
        )

    def log_end(
        self,
        request_id: str,
        started_at: float,
    ) -> None:

        duration_ms = (
            time.monotonic()
            - started_at
        ) * 1000

        self.logger.info(
            "Update finished: request_id=%s duration_ms=%.2f",
            request_id,
            duration_ms,
        )

    # ------------------------------------------------------------------
    # Process
    # ------------------------------------------------------------------

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        request_id = (
            self.create_request_id()
        )

        started_at = time.monotonic()

        context.user_data[
            "request_id"
        ] = request_id

        context.user_data[
            "request_started_at"
        ] = started_at

        self.log_start(
            update,
            request_id,
        )

        # This middleware never blocks a valid update.
        # It only adds observability.
        return True

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        return await self.process(
            update,
            context,
        )


def get_request_id(
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:

    value = context.user_data.get(
        "request_id"
    )

    if value is None:
        return None

    return str(value)


__all__ = [
    "LoggingMiddleware",
    "get_request_id",
]