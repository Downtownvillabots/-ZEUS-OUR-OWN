"""
bot.middleware.errors

Centralized error handling utilities.

Responsibilities:
    - Catch unexpected handler errors.
    - Log exceptions with request/user information.
    - Prevent sensitive exception details from reaching users.
    - Provide safe user-facing error responses.
    - Support optional error callbacks.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, Awaitable, Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes,
)

from .logging import get_request_id


logger = logging.getLogger(
    "bot.middleware.errors"
)


ErrorCallback = Callable[
    [
        Update,
        ContextTypes.DEFAULT_TYPE,
        Exception,
    ],
    Any,
]


class ErrorMiddleware:
    """
    Central application error middleware.

    Handler errors should normally reach this layer rather than
    being silently swallowed.
    """

    def __init__(
        self,
        *,
        error_callback: Optional[
            ErrorCallback
        ] = None,
        expose_details: bool = False,
        user_message: str = (
            "⚠️ Something went wrong while "
            "processing your request.\n\n"
            "Please try again in a moment."
        ),
    ) -> None:

        self.error_callback = (
            error_callback
        )

        self.expose_details = (
            bool(expose_details)
        )

        self.user_message = (
            user_message
        )

    # ------------------------------------------------------------------
    # Error context
    # ------------------------------------------------------------------

    @staticmethod
    def get_context(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> dict[str, Any]:

        user = update.effective_user
        chat = update.effective_chat

        return {
            "request_id": get_request_id(
                context
            ),
            "user_id": (
                user.id
                if user
                else None
            ),
            "username": (
                user.username
                if user
                else None
            ),
            "chat_id": (
                chat.id
                if chat
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_exception(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error: Exception,
    ) -> None:

        error_context = (
            self.get_context(
                update,
                context,
            )
        )

        self.logger.exception(
            "Unhandled bot exception: "
            "context=%s error=%s",
            error_context,
            error,
        )

    @property
    def logger(self) -> logging.Logger:
        return logger

    # ------------------------------------------------------------------
    # Safe response
    # ------------------------------------------------------------------

    async def send_user_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error: Exception,
    ) -> None:

        message = self.user_message

        if self.expose_details:

            safe_error = (
                str(error)
                .replace(
                    "<",
                    "&lt;",
                )
                .replace(
                    ">",
                    "&gt;",
                )
            )

            if len(safe_error) > 500:
                safe_error = (
                    safe_error[:500]
                    + "..."
                )

            message += (
                "\n\n"
                f"`{safe_error}`"
            )

        try:

            callback = (
                update.callback_query
            )

            if callback is not None:

                try:
                    await callback.answer(
                        "⚠️ An error occurred.",
                        show_alert=True,
                    )
                except Exception:
                    pass

                if callback.message is not None:

                    await callback.message.reply_text(
                        message,
                        parse_mode=ParseMode.MARKDOWN,
                    )

                return

            if update.effective_message is not None:

                await update.effective_message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN,
                )

        except Exception:

            self.logger.exception(
                "Unable to send user error message."
            )

    # ------------------------------------------------------------------
    # Process
    # ------------------------------------------------------------------

    async def process_error(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        error: Exception,
    ) -> None:

        self.log_exception(
            update,
            context,
            error,
        )

        if self.error_callback is not None:

            try:

                result = self.error_callback(
                    update,
                    context,
                    error,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    await result

            except Exception:

                self.logger.exception(
                    "Custom error callback failed."
                )

        await self.send_user_error(
            update,
            context,
            error,
        )

    # ------------------------------------------------------------------
    # Callable middleware interface
    # ------------------------------------------------------------------

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        try:
            return True

        except Exception as error:

            await self.process_error(
                update,
                context,
                error,
            )

            return False


# ============================================================================
# Error handler adapter for python-telegram-bot
# ============================================================================

def create_error_handler(
    *,
    error_callback: Optional[
        ErrorCallback
    ] = None,
    expose_details: bool = False,
) -> Callable[
    [
        Update,
        ContextTypes.DEFAULT_TYPE,
    ],
    Awaitable[None],
]:
    """
    Create a PTB-compatible application error handler.

    Example:

        application.add_error_handler(
            create_error_handler()
        )
    """

    middleware = ErrorMiddleware(
        error_callback=error_callback,
        expose_details=expose_details,
    )

    async def handler(
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:

        if not isinstance(
            update,
            Update,
        ):

            middleware.logger.error(
                "Error handler received invalid update: %r",
                update,
            )

            return

        error = getattr(
            context,
            "error",
            None,
        )

        if error is None:

            error = RuntimeError(
                "Unknown Telegram update error."
            )

        await middleware.process_error(
            update,
            context,
            error,
        )

    return handler


# ============================================================================
# Safe exception utility
# ============================================================================

def format_exception_for_log(
    error: BaseException,
) -> str:

    return "".join(
        traceback.format_exception(
            type(error),
            error,
            error.__traceback__,
        )
    )


def safe_error_text(
    error: Exception,
    *,
    maximum_length: int = 500,
) -> str:

    text = str(error).strip()

    if not text:
        text = (
            "Unknown error"
        )

    text = text.replace(
        "\n",
        " ",
    )

    if len(text) > maximum_length:

        text = (
            text[:maximum_length]
            + "..."
        )

    return text


__all__ = [
    "ErrorMiddleware",
    "create_error_handler",
    "format_exception_for_log",
    "safe_error_text",
]