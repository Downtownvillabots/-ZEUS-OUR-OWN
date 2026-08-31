"""
bot/handlers/errors.py

CENTRALIZED ERROR HANDLING – ULTIMATE EDITION

Responsibilities
----------------
- Catch and classify Telegram/Pyrogram and application exceptions
- Log errors with rich context (user, chat, handler, traceback)
- Provide safe, user‑friendly error messages (never expose internals)
- Handle retry‑able errors (FloodWait, timeouts) with automatic backoff
- Support decorator‑based error handling for handlers and callbacks
- Include an error middleware for service‑level execution
- Allow admin notifications for critical errors
- Fully compatible with Pyrogram v2 (uses FloodWait, not RetryAfter)

All error responses are sanitised and truncated to avoid leaking secrets.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Awaitable, TypeVar, Union

from pyrogram import Client
from pyrogram.errors import (
    BadRequest,
    FloodWait,
    Forbidden,
    MessageNotModified,
    RPCError,
    Unauthorized,
)
from pyrogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

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
DEFAULT_RETRY_DELAY = 5  # seconds
MAX_RETRY_ATTEMPTS = 3

# -----------------------------------------------------------------------------
# Error Context
# -----------------------------------------------------------------------------

@dataclass
class ErrorContext:
    """Rich context for an error occurrence."""
    user_id: Optional[int] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    callback_id: Optional[str] = None
    command: Optional[str] = None
    handler: Optional[str] = None
    update_type: Optional[str] = None
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    retry_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

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
            "retry_count": self.retry_count,
        }


def context_from_message(message: Optional[Message]) -> ErrorContext:
    if message is None:
        return ErrorContext(update_type="message")
    ctx = ErrorContext(update_type="message")
    if message.from_user:
        ctx.user_id = int(message.from_user.id)
    if message.chat:
        ctx.chat_id = int(message.chat.id)
    if message.id:
        ctx.message_id = int(message.id)
    if message.command:
        ctx.command = message.command[0] if message.command else None
    return ctx


def context_from_callback(callback: Optional[CallbackQuery]) -> ErrorContext:
    if callback is None:
        return ErrorContext(update_type="callback")
    ctx = ErrorContext(update_type="callback")
    if callback.from_user:
        ctx.user_id = int(callback.from_user.id)
    if callback.message:
        ctx.chat_id = int(callback.message.chat.id)
        ctx.message_id = int(callback.message.id)
    if callback.id:
        ctx.callback_id = callback.id
    return ctx


def enrich_context(context: ErrorContext, exception: BaseException,
                   handler: Optional[str] = None) -> ErrorContext:
    context.exception_type = type(exception).__name__
    context.exception_message = str(exception)
    if handler:
        context.handler = handler
    return context

# -----------------------------------------------------------------------------
# Sanitisation
# -----------------------------------------------------------------------------

def sanitise_exception_text(exception: BaseException) -> str:
    """Remove any sensitive information from exception strings."""
    text = str(exception)
    if not text:
        return ""
    sensitive = ("api_hash", "api_id", "bot_token", "token=", "password",
                 "secret", "authorization", "bearer ")
    lowered = text.lower()
    if any(pat in lowered for pat in sensitive):
        return "Sensitive error details suppressed."
    return text[:MAX_ERROR_TEXT]


def get_traceback(exception: BaseException) -> str:
    try:
        return "".join(traceback.format_exception(
            type(exception), exception, exception.__traceback__
        ))
    except Exception:
        return f"{type(exception).__name__}: {exception}"

# -----------------------------------------------------------------------------
# Exception Classification
# -----------------------------------------------------------------------------

def is_flood_error(exception: BaseException) -> bool:
    return isinstance(exception, (FloodWait,))  # RetryAfter is obsolete


def is_permission_error(exception: BaseException) -> bool:
    return isinstance(exception, Forbidden)


def is_auth_error(exception: BaseException) -> bool:
    return isinstance(exception, Unauthorized)


def is_bad_request(exception: BaseException) -> bool:
    return isinstance(exception, BadRequest)


def is_rpc_error(exception: BaseException) -> bool:
    return isinstance(exception, RPCError)


def is_message_not_modified(exception: BaseException) -> bool:
    return isinstance(exception, MessageNotModified)


def get_retry_seconds(exception: BaseException) -> Optional[int]:
    """Extract flood wait seconds from FloodWait."""
    if isinstance(exception, FloodWait):
        # FloodWait has attribute 'value' in newer versions, or 'x'
        value = getattr(exception, 'value', None) or getattr(exception, 'x', None)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    return None

# -----------------------------------------------------------------------------
# User‑Facing Error Messages
# -----------------------------------------------------------------------------

def error_to_user_message(exception: BaseException) -> str:
    if is_flood_error(exception):
        seconds = get_retry_seconds(exception)
        if seconds is None:
            return USER_ERROR_RATE_LIMIT
        if seconds < 60:
            return f"⏳ Telegram is rate‑limiting the bot.\n\nPlease wait about <b>{seconds}</b> seconds."
        minutes = max(1, seconds // 60)
        return f"⏳ Telegram is rate‑limiting the bot.\n\nPlease wait about <b>{minutes}</b> minute(s)."
    if is_permission_error(exception):
        return USER_ERROR_PERMISSION
    if is_auth_error(exception):
        return "🔐 Telegram authentication failed.\n\nPlease contact the administrator."
    if is_message_not_modified(exception):
        return ""
    if isinstance(exception, FileNotFoundError):
        return USER_ERROR_NOT_FOUND
    if isinstance(exception, (TimeoutError, ConnectionError)):
        return USER_ERROR_TEMPORARY
    if is_bad_request(exception):
        text = str(exception).lower()
        if "not found" in text:
            return USER_ERROR_NOT_FOUND
        if "permission" in text:
            return USER_ERROR_PERMISSION
        if "message is not modified" in text:
            return ""
        return USER_ERROR_GENERIC
    return USER_ERROR_GENERIC

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

def log_exception(exception: BaseException,
                  context: Optional[ErrorContext] = None,
                  level: int = logging.ERROR) -> None:
    ctx = context or ErrorContext()
    logger.log(level,
               "Unhandled application error | context=%s | error=%s",
               ctx.as_dict(),
               sanitise_exception_text(exception),
               exc_info=True)


def log_warning(message: str, context: Optional[ErrorContext] = None) -> None:
    logger.warning("%s | context=%s", message, context.as_dict() if context else {})


def log_info(message: str, context: Optional[ErrorContext] = None) -> None:
    logger.info("%s | context=%s", message, context.as_dict() if context else {})

# -----------------------------------------------------------------------------
# Sending Error Responses
# -----------------------------------------------------------------------------

async def send_error_message(message: Optional[Message],
                             exception: BaseException) -> bool:
    if message is None:
        return False
    text = error_to_user_message(exception)
    if not text:
        return False
    try:
        await message.reply_text(text)
        return True
    except Exception:
        logger.exception("Unable to send error response.")
        return False


async def answer_callback_error(callback: Optional[CallbackQuery],
                                exception: BaseException) -> bool:
    if callback is None:
        return False
    text = error_to_user_message(exception)
    if not text:
        return True
    try:
        await callback.answer(text, show_alert=True)
        return True
    except Exception:
        logger.exception("Unable to answer callback error.")
        return False

# -----------------------------------------------------------------------------
# Main Error Handlers
# -----------------------------------------------------------------------------

async def handle_message_error(client: Client,
                               message: Optional[Message],
                               exception: BaseException,
                               handler: Optional[str] = None) -> None:
    context = context_from_message(message)
    enrich_context(context, exception, handler)
    log_exception(exception, context)
    await send_error_message(message, exception)


async def handle_callback_error(client: Client,
                                callback: Optional[CallbackQuery],
                                exception: BaseException,
                                handler: Optional[str] = None) -> None:
    context = context_from_callback(callback)
    enrich_context(context, exception, handler)
    log_exception(exception, context)
    await answer_callback_error(callback, exception)

# -----------------------------------------------------------------------------
# Retry Decorator
# -----------------------------------------------------------------------------

T = TypeVar('T', bound=Callable[..., Awaitable[Any]])

def with_retry(max_attempts: int = MAX_RETRY_ATTEMPTS,
               base_delay: int = DEFAULT_RETRY_DELAY,
               backoff_factor: float = 2.0,
               retry_on: tuple[type[Exception], ...] = (FloodWait, TimeoutError, ConnectionError)):
    """
    Decorator to automatically retry a handler or service on specific exceptions.
    """
    def decorator(func: T) -> T:
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    last_exception = exc
                    delay = base_delay * (backoff_factor ** (attempt - 1))
                    # If it's a FloodWait, use the exact wait time if available
                    if isinstance(exc, FloodWait):
                        flood_delay = get_retry_seconds(exc)
                        if flood_delay is not None:
                            delay = min(flood_delay, 60)  # cap at 60s to avoid too long
                    logger.warning("Retry attempt %d/%d for %s after %.1fs: %s",
                                   attempt, max_attempts, func.__name__, delay, exc)
                    await asyncio.sleep(delay)
                    if attempt == max_attempts:
                        raise last_exception
            # Should not reach here
            raise last_exception
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator

# -----------------------------------------------------------------------------
# Decorators for Handlers (with error handling)
# -----------------------------------------------------------------------------

def with_error_handling(handler_name: Optional[str] = None):
    """
    Decorator for normal message handlers. Catches exceptions and sends user‑friendly errors.
    """
    def decorator(func: T) -> T:
        async def wrapper(client: Client, message: Message, *args, **kwargs):
            try:
                return await func(client, message, *args, **kwargs)
            except Exception as exc:
                await handle_message_error(
                    client, message, exc,
                    handler=handler_name or func.__name__
                )
                return None
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


def with_callback_error_handling(handler_name: Optional[str] = None):
    """
    Decorator for callback handlers.
    """
    def decorator(func: T) -> T:
        async def wrapper(client: Client, callback_query: CallbackQuery, *args, **kwargs):
            try:
                return await func(client, callback_query, *args, **kwargs)
            except Exception as exc:
                await handle_callback_error(
                    client, callback_query, exc,
                    handler=handler_name or func.__name__
                )
                return None
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator

# -----------------------------------------------------------------------------
# Error Middleware
# -----------------------------------------------------------------------------

class ErrorMiddleware:
    """
    Reusable middleware for safe execution of services and operations.
    """
    def __init__(self, client: Optional[Client] = None):
        self.client = client

    async def execute(self, operation, context: Optional[ErrorContext] = None,
                      fallback=None):
        try:
            result = operation()
            if hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as exc:
            log_exception(exc, context)
            return fallback

    async def message_operation(self, operation, message: Optional[Message],
                                handler: Optional[str] = None):
        ctx = context_from_message(message)
        return await self.execute(operation, ctx)

    async def callback_operation(self, operation, callback: Optional[CallbackQuery],
                                 handler: Optional[str] = None):
        ctx = context_from_callback(callback)
        return await self.execute(operation, ctx)

# -----------------------------------------------------------------------------
# Global Error Handler
# -----------------------------------------------------------------------------

async def global_error_handler(client: Client, exception: Exception):
    """
    Fallback for uncaught exceptions. Should be wired in the main app.
    """
    ctx = ErrorContext(update_type="global")
    log_exception(exception, ctx)
    if isinstance(exception, FloodWait):
        seconds = get_retry_seconds(exception)
        logger.warning("Global flood wait for %s seconds", seconds)
    elif isinstance(exception, Forbidden):
        logger.warning("Global permission error")
    elif isinstance(exception, BadRequest):
        logger.warning("Global bad request")

# -----------------------------------------------------------------------------
# Admin Error Reporting
# -----------------------------------------------------------------------------

def format_admin_error(exception: BaseException,
                       context: Optional[ErrorContext] = None) -> str:
    """Produce a detailed (but still sanitised) error message for administrators."""
    exc_type = type(exception).__name__
    exc_msg = sanitise_exception_text(exception) or "No message"
    lines = [
        "<b>🚨 Application Error</b>",
        "",
        f"Type: <code>{exc_type}</code>",
        f"Error: <code>{exc_msg}</code>",
    ]
    if context:
        if context.user_id is not None:
            lines.append(f"User: <code>{context.user_id}</code>")
        if context.chat_id is not None:
            lines.append(f"Chat: <code>{context.chat_id}</code>")
        if context.message_id is not None:
            lines.append(f"Message: <code>{context.message_id}</code>")
        if context.handler:
            lines.append(f"Handler: <code>{context.handler}</code>")
    return "\n".join(lines)


def escape_html(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# -----------------------------------------------------------------------------
# Service Error Classes
# -----------------------------------------------------------------------------

class ServiceError(Exception):
    """Base application service error."""

class DatabaseError(ServiceError):
    """Database operation failed."""

class ValidationError(ServiceError):
    """Input validation failed."""

class NotFoundError(ServiceError):
    """Requested entity not found."""

class PermissionError(ServiceError):
    """Application-level permission failure."""

class ConfigurationError(ServiceError):
    """Required configuration missing."""


def service_error_message(exception: BaseException) -> str:
    if isinstance(exception, ValidationError):
        return "⚠️ <b>Invalid request.</b>\n\nPlease check your input and try again."
    if isinstance(exception, NotFoundError):
        return USER_ERROR_NOT_FOUND
    if isinstance(exception, PermissionError):
        return USER_ERROR_PERMISSION
    if isinstance(exception, ConfigurationError):
        return "⚙️ This feature is not configured yet.\n\nPlease contact the administrator."
    if isinstance(exception, DatabaseError):
        return USER_ERROR_TEMPORARY
    return error_to_user_message(exception)


async def safe_service_call(operation, context: Optional[ErrorContext] = None,
                            default=None):
    """Execute a service/database call safely, logging and returning default on error."""
    try:
        result = operation()
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception as exc:
        log_exception(exc, context)
        return default

# -----------------------------------------------------------------------------
# Registration (no-op, but kept for consistency)
# -----------------------------------------------------------------------------

def register(app: Client) -> None:
    logger.info("Centralized error handling registered (no handlers added).")

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

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
    "with_retry",
    "format_admin_error",
    "get_traceback",
    "register",
]
