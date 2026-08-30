"""
bot/handlers/errors.py

Centralized error handling.

Responsibilities
----------------
- Catch unhandled Telegram/Pyrogram exceptions
- Log errors with useful context
- Return safe user-facing messages
- Avoid exposing stack traces/secrets
- Handle common Telegram errors separately
- Handle database/service failures
- Provide reusable error helpers
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client
from pyrogram.errors import (
    BadRequest,
    FloodWait,
    Forbidden,
    MessageNotModified,
    RPCError,
    RetryAfter,
    Unauthorized,
)
from pyrogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

USER_ERROR_GENERIC = (
    "❌ Something went wrong while processing your request.\n\n"
    "Please try again in a moment."
)

USER_ERROR_TEMPORARY = (
    "⚠️ The service is temporarily unavailable.\n\n"
    "Please try again shortly."
)

USER_ERROR_PERMISSION = (
    "🚫 I don't have permission to perform that action."
)

USER_ERROR_NOT_FOUND = (
    "🔎 The requested item could not be found."
)

USER_ERROR_RATE_LIMIT = (
    "⏳ Too many requests.\n\n"
    "Please wait a little and try again."
)

USER_ERROR_EXPIRED = (
    "⌛ This action has expired.\n\n"
    "Please start the operation again."
)

USER_ERROR_MAINTENANCE = (
    "🛠️ The bot is currently under maintenance.\n\n"
    "Please try again later."
)

MAX_ERROR_TEXT = 500


# ============================================================================
# Error context
# ============================================================================

@dataclass
class ErrorContext:
    """
    Context captured when an exception occurs.
    """

    user_id: Optional[int] = None

    chat_id: Optional[int] = None

    message_id: Optional[int] = None

    callback_id: Optional[str] = None

    command: Optional[str] = None

    handler: Optional[str] = None

    update_type: Optional[str] = None

    exception_type: Optional[str] = None

    exception_message: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:

        return {
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "callback_id": self.callback_id,
            "command": self.command,
            "handler": self.handler,
            "update_type": self.update_type,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
        }


# ============================================================================
# Context builders
# ============================================================================

def context_from_message(
    message: Optional[Message],
) -> ErrorContext:

    if message is None:
        return ErrorContext(
            update_type="message"
        )

    user_id = None

    if message.from_user:

        user_id = int(
            message.from_user.id
        )

    chat_id = None

    if message.chat:

        chat_id = int(
            message.chat.id
        )

    command = None

    if message.command:

        command = (
            message.command[0]
            if message.command
            else None
        )

    return ErrorContext(
        user_id=user_id,
        chat_id=chat_id,
        message_id=(
            int(message.id)
            if message.id
            else None
        ),
        command=command,
        update_type="message",
    )


def context_from_callback(
    callback: Optional[CallbackQuery],
) -> ErrorContext:

    if callback is None:
        return ErrorContext(
            update_type="callback"
        )

    user_id = None

    if callback.from_user:

        user_id = int(
            callback.from_user.id
        )

    chat_id = None
    message_id = None

    if callback.message:

        chat_id = int(
            callback.message.chat.id
        )

        message_id = int(
            callback.message.id
        )

    return ErrorContext(
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        callback_id=callback.id,
        update_type="callback",
    )


def enrich_context(
    context: ErrorContext,
    exception: BaseException,
    *,
    handler: Optional[str] = None,
) -> ErrorContext:

    context.exception_type = type(
        exception
    ).__name__

    context.exception_message = str(
        exception
    )

    if handler:

        context.handler = handler

    return context


# ============================================================================
# Error sanitization
# ============================================================================

def sanitize_exception_text(
    exception: BaseException,
) -> str:
    """
    Prevent sensitive values from accidentally being displayed.

    Detailed exception text belongs in logs, not Telegram responses.
    """

    text = str(
        exception
    )

    if not text:
        return ""

    # Never expose potentially sensitive Telegram/API internals.
    sensitive_words = (
        "api_hash",
        "api_id",
        "bot_token",
        "token=",
        "password",
        "passwd",
        "secret",
        "authorization",
        "bearer ",
    )

    lowered = text.lower()

    if any(
        item in lowered
        for item in sensitive_words
    ):

        return "Sensitive error details suppressed."

    return text[
        :MAX_ERROR_TEXT
    ]


# ============================================================================
# Exception classification
# ============================================================================

def is_flood_error(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        (
            FloodWait,
            RetryAfter,
        ),
    )


def is_permission_error(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        Forbidden,
    )


def is_auth_error(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        Unauthorized,
    )


def is_bad_request(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        BadRequest,
    )


def is_rpc_error(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        RPCError,
    )


def is_message_not_modified(
    exception: BaseException,
) -> bool:

    return isinstance(
        exception,
        MessageNotModified,
    )


# ============================================================================
# Retry helpers
# ============================================================================

def get_retry_seconds(
    exception: BaseException,
) -> Optional[int]:

    value = getattr(
        exception,
        "value",
        None,
    )

    if value is None:

        value = getattr(
            exception,
            "x",
            None,
        )

    try:

        if value is None:
            return None

        return max(
            0,
            int(value),
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


def retry_message(
    exception: BaseException,
) -> str:

    seconds = get_retry_seconds(
        exception
    )

    if seconds is None:

        return USER_ERROR_RATE_LIMIT

    if seconds < 60:

        return (
            "⏳ Telegram is rate-limiting the bot.\n\n"
            f"Please wait about <b>{seconds}</b> seconds."
        )

    minutes = max(
        1,
        seconds // 60,
    )

    return (
        "⏳ Telegram is rate-limiting the bot.\n\n"
        f"Please wait about <b>{minutes}</b> minute(s)."
    )


# ============================================================================
# User-facing error mapping
# ============================================================================

def error_to_user_message(
    exception: BaseException,
) -> str:
    """
    Convert an exception into a safe Telegram message.
    """

    if is_flood_error(
        exception
    ):

        return retry_message(
            exception
        )

    if is_permission_error(
        exception
    ):

        return USER_ERROR_PERMISSION

    if is_auth_error(
        exception
    ):

        return (
            "🔐 Telegram authentication failed.\n\n"
            "Please contact the administrator."
        )

    if is_message_not_modified(
        exception
    ):

        return ""

    if isinstance(
        exception,
        FileNotFoundError,
    ):

        return USER_ERROR_NOT_FOUND

    if isinstance(
        exception,
        TimeoutError,
    ):

        return USER_ERROR_TEMPORARY

    if isinstance(
        exception,
        ConnectionError,
    ):

        return USER_ERROR_TEMPORARY

    if is_bad_request(
        exception
    ):

        text = str(
            exception
        ).lower()

        if "not found" in text:

            return USER_ERROR_NOT_FOUND

        if "permission" in text:

            return USER_ERROR_PERMISSION

        if "message is not modified" in text:

            return ""

        return USER_ERROR_GENERIC

    return USER_ERROR_GENERIC


# ============================================================================
# Logging
# ============================================================================

def log_exception(
    exception: BaseException,
    context: Optional[ErrorContext] = None,
    *,
    level: int = logging.ERROR,
) -> None:

    if context is None:

        context = ErrorContext()

    payload = context.as_dict()

    logger.log(
        level,
        "Unhandled application error | context=%s | error=%s",
        payload,
        sanitize_exception_text(
            exception
        ),
        exc_info=True,
    )


def log_warning(
    message: str,
    *,
    context: Optional[ErrorContext] = None,
) -> None:

    logger.warning(
        "%s | context=%s",
        message,
        context.as_dict()
        if context
        else {},
    )


def log_info(
    message: str,
    *,
    context: Optional[ErrorContext] = None,
) -> None:

    logger.info(
        "%s | context=%s",
        message,
        context.as_dict()
        if context
        else {},
    )


# ============================================================================
# Telegram error responses
# ============================================================================

async def send_error_message(
    message: Optional[Message],
    exception: BaseException,
) -> bool:

    if message is None:
        return False

    text = error_to_user_message(
        exception
    )

    if not text:
        return False

    try:

        await message.reply_text(
            text
        )

        return True

    except Exception:

        logger.exception(
            "Unable to send error response."
        )

        return False


async def answer_callback_error(
    callback: Optional[CallbackQuery],
    exception: BaseException,
) -> bool:

    if callback is None:
        return False

    text = error_to_user_message(
        exception
    )

    if not text:
        return True

    try:

        await callback.answer(
            text,
            show_alert=True,
        )

        return True

    except Exception:

        logger.exception(
            "Unable to answer callback error."
        )

        return False


async def handle_message_error(
    client: Client,
    message: Optional[Message],
    exception: BaseException,
    *,
    handler: Optional[str] = None,
) -> None:

    context = context_from_message(
        message
    )

    enrich_context(
        context,
        exception,
        handler=handler,
    )

    log_exception(
        exception,
        context,
    )

    await send_error_message(
        message,
        exception,
    )


async def handle_callback_error(
    client: Client,
    callback: Optional[CallbackQuery],
    exception: BaseException,
    *,
    handler: Optional[str] = None,
) -> None:

    context = context_from_callback(
        callback
    )

    enrich_context(
        context,
        exception,
        handler=handler,
    )

    log_exception(
        exception,
        context,
    )

    await answer_callback_error(
        callback,
        exception,
    )


# ============================================================================
# Specific Telegram error handlers
# ============================================================================

async def handle_flood_wait(
    client: Client,
    exception: BaseException,
    *,
    context: Optional[ErrorContext] = None,
) -> None:

    seconds = get_retry_seconds(
        exception
    )

    log_warning(
        (
            "Telegram flood wait encountered"
            + (
                f" ({seconds}s)"
                if seconds is not None
                else ""
            )
        ),
        context=context,
    )


async def handle_forbidden(
    client: Client,
    exception: BaseException,
    *,
    context: Optional[ErrorContext] = None,
) -> None:

    log_warning(
        "Telegram permission/forbidden error.",
        context=context,
    )


async def handle_bad_request(
    client: Client,
    exception: BaseException,
    *,
    context: Optional[ErrorContext] = None,
) -> None:

    log_warning(
        "Telegram bad request.",
        context=context,
    )


# ============================================================================
# Error middleware
# ============================================================================

class ErrorMiddleware:
    """
    Reusable application error middleware.

    The middleware is intentionally framework-light so it can be used
    around handlers, services, jobs, and callbacks.
    """

    def __init__(
        self,
        client: Optional[Client] = None,
    ) -> None:

        self.client = client

    async def execute(
        self,
        operation,
        *,
        context: Optional[ErrorContext] = None,
        fallback=None,
    ):

        try:

            result = operation()

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return result

        except Exception as exception:

            log_exception(
                exception,
                context,
            )

            if fallback is not None:

                return fallback

            return None

    async def message(
        self,
        operation,
        message: Optional[Message],
        *,
        handler: Optional[str] = None,
    ):

        context = context_from_message(
            message
        )

        return await self.execute(
            operation,
            context=enrich_context(
                context,
                Exception(),
                handler=handler,
            )
            if False
            else context,
        )

    async def callback(
        self,
        operation,
        callback: Optional[CallbackQuery],
        *,
        handler: Optional[str] = None,
    ):

        context = context_from_callback(
            callback
        )

        return await self.execute(
            operation,
            context=context,
        )


# ============================================================================
# Decorator helpers
# ============================================================================

def with_error_handling(
    *,
    handler_name: Optional[str] = None,
):
    """
    Decorator for normal async handlers.

    Example:

        @with_error_handling(handler_name="search")
        async def search_handler(client, message):
            ...
    """

    def decorator(function):

        async def wrapper(
            client: Client,
            message: Message,
            *args,
            **kwargs,
        ):

            try:

                return await function(
                    client,
                    message,
                    *args,
                    **kwargs,
                )

            except Exception as exception:

                await handle_message_error(
                    client,
                    message,
                    exception,
                    handler=(
                        handler_name
                        or getattr(
                            function,
                            "__name__",
                            None,
                        )
                    ),
                )

                return None

        wrapper.__name__ = getattr(
            function,
            "__name__",
            "wrapped_handler",
        )

        wrapper.__doc__ = getattr(
            function,
            "__doc__",
            None,
        )

        return wrapper

    return decorator


def with_callback_error_handling(
    *,
    handler_name: Optional[str] = None,
):
    """
    Decorator for callback handlers.
    """

    def decorator(function):

        async def wrapper(
            client: Client,
            callback_query: CallbackQuery,
            *args,
            **kwargs,
        ):

            try:

                return await function(
                    client,
                    callback_query,
                    *args,
                    **kwargs,
                )

            except Exception as exception:

                await handle_callback_error(
                    client,
                    callback_query,
                    exception,
                    handler=(
                        handler_name
                        or getattr(
                            function,
                            "__name__",
                            None,
                        )
                    ),
                )

                return None

        wrapper.__name__ = getattr(
            function,
            "__name__",
            "wrapped_callback_handler",
        )

        wrapper.__doc__ = getattr(
            function,
            "__doc__",
            None,
        )

        return wrapper

    return decorator


# ============================================================================
# Global Pyrogram error handler
# ============================================================================

async def global_error_handler(
    client: Client,
    exception: Exception,
):
    """
    Global fallback.

    Note:
    Pyrogram's exact global-error registration API can differ depending
    on the application architecture. Keeping the handler independent
    allows app.py to wire it appropriately.
    """

    context = ErrorContext(
        update_type="global"
    )

    log_exception(
        exception,
        context,
    )

    if isinstance(
        exception,
        FloodWait,
    ):

        await handle_flood_wait(
            client,
            exception,
            context=context,
        )

        return

    if isinstance(
        exception,
        Forbidden,
    ):

        await handle_forbidden(
            client,
            exception,
            context=context,
        )

        return

    if isinstance(
        exception,
        BadRequest,
    ):

        await handle_bad_request(
            client,
            exception,
            context=context,
        )

        return


# ============================================================================
# Database/service error helpers
# ============================================================================

class ServiceError(Exception):
    """
    Base application service error.
    """


class DatabaseError(
    ServiceError
):
    """
    Database operation failed.
    """


class ValidationError(
    ServiceError
):
    """
    Input validation failed.
    """


class NotFoundError(
    ServiceError
):
    """
    Requested entity does not exist.
    """


class PermissionError(
    ServiceError
):
    """
    Application-level permission failure.
    """


class ConfigurationError(
    ServiceError
):
    """
    Required configuration is missing.
    """


def service_error_message(
    exception: BaseException,
) -> str:

    if isinstance(
        exception,
        ValidationError,
    ):

        return (
            "⚠️ <b>Invalid request.</b>\n\n"
            "Please check your input and try again."
        )

    if isinstance(
        exception,
        NotFoundError,
    ):

        return USER_ERROR_NOT_FOUND

    if isinstance(
        exception,
        PermissionError,
    ):

        return USER_ERROR_PERMISSION

    if isinstance(
        exception,
        ConfigurationError,
    ):

        return (
            "⚙️ This feature is not configured yet.\n\n"
            "Please contact the administrator."
        )

    if isinstance(
        exception,
        DatabaseError,
    ):

        return USER_ERROR_TEMPORARY

    return error_to_user_message(
        exception
    )


# ============================================================================
# Safe service execution
# ============================================================================

async def safe_service_call(
    operation,
    *,
    context: Optional[ErrorContext] = None,
    default=None,
):
    """
    Execute service/database operation safely.

    Exceptions are logged and converted to a default result.
    """

    try:

        result = operation()

        if hasattr(
            result,
            "__await__",
        ):

            result = await result

        return result

    except Exception as exception:

        log_exception(
            exception,
            context,
        )

        return default


# ============================================================================
# Error reporting
# ============================================================================

def format_admin_error(
    exception: BaseException,
    context: Optional[ErrorContext] = None,
) -> str:
    """
    Create an administrator-friendly diagnostic message.

    This should only be sent to trusted administrators.
    """

    exception_type = type(
        exception
    ).__name__

    exception_text = (
        sanitize_exception_text(
            exception
        )
        or "No message"
    )

    lines = [
        "<b>🚨 Application Error</b>",
        "",
        f"Type: <code>{exception_type}</code>",
        f"Error: <code>{escape_html(exception_text)}</code>",
    ]

    if context:

        if context.user_id is not None:

            lines.append(
                f"User: <code>{context.user_id}</code>"
            )

        if context.chat_id is not None:

            lines.append(
                f"Chat: <code>{context.chat_id}</code>"
            )

        if context.message_id is not None:

            lines.append(
                f"Message: <code>{context.message_id}</code>"
            )

        if context.handler:

            lines.append(
                f"Handler: <code>"
                f"{escape_html(context.handler)}"
                f"</code>"
            )

    return "\n".join(
        lines
    )


def escape_html(
    value: Any,
) -> str:

    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============================================================================
# Traceback utility
# ============================================================================

def get_traceback(
    exception: BaseException,
) -> str:

    try:

        return "".join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            )
        )

    except Exception:

        return (
            f"{type(exception).__name__}: "
            f"{exception}"
        )


def log_full_traceback(
    exception: BaseException,
    context: Optional[ErrorContext] = None,
) -> None:

    logger.error(
        "Full exception traceback | context=%s\n%s",
        context.as_dict()
        if context
        else {},
        get_traceback(
            exception
        ),
    )


# ============================================================================
# Registration
# ============================================================================

def register(
    app: Client,
) -> None:
    """
    Error module initialization.

    Most error handling is attached directly to handlers through the
    decorators/helpers above.

    This function intentionally does not register a catch-all message
    handler because doing so can interfere with normal handler ordering.
    """

    logger.info(
        "Initialized centralized error handling."
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ErrorContext",
    "ErrorMiddleware",
    "ServiceError",
    "DatabaseError",
    "ValidationError",
    "NotFoundError",
    "PermissionError",
    "ConfigurationError",
    "context_from_message",
    "context_from_callback",
    "error_to_user_message",
    "service_error_message",
    "log_exception",
    "log_warning",
    "log_info",
    "handle_message_error",
    "handle_callback_error",
    "global_error_handler",
    "safe_service_call",
    "with_error_handling",
    "with_callback_error_handling",
    "format_admin_error",
    "get_traceback",
    "register",
]