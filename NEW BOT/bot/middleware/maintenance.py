"""
bot.middleware.maintenance

Global maintenance-mode middleware.

Responsibilities
----------------
- Block normal users while maintenance mode is active
- Always allow configured administrators
- Read the canonical maintenance state
- Show a consistent maintenance UI
- Support message and callback updates
- Avoid duplicating maintenance logic in every handler

This module uses bot.handlers.maintenance as the state/business layer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram import Client
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.middleware import MiddlewareContext

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

MAINTENANCE_CONTEXT_KEY = "maintenance_state"
MAINTENANCE_BLOCKED_KEY = "maintenance_blocked"

DEFAULT_MESSAGE = (
    "🛠️ <b>Bot Under Maintenance</b>\n\n"
    "We're currently performing maintenance.\n"
    "Please try again later."
)


# ============================================================================
# Lazy service import
# ============================================================================

def get_maintenance_service():
    """
    Import the handler/service lazily.

    Lazy import prevents circular imports during application startup.
    """

    try:

        from bot.handlers import maintenance

        return maintenance

    except Exception:

        logger.exception(
            "Unable to load maintenance service."
        )

        return None


# ============================================================================
# State access
# ============================================================================

async def get_state(
    client: Client,
):
    """
    Retrieve the canonical maintenance state.
    """

    service = get_maintenance_service()

    if service is None:
        return None

    getter = getattr(
        service,
        "get_maintenance_state",
        None,
    )

    if getter is None:
        return None

    try:

        return await getter(
            client
        )

    except Exception:

        logger.exception(
            "Unable to retrieve maintenance state."
        )

        return None


async def maintenance_enabled(
    client: Client,
) -> bool:

    service = get_maintenance_service()

    if service is None:
        return False

    checker = getattr(
        service,
        "is_maintenance_mode",
        None,
    )

    if checker is None:

        state = await get_state(
            client
        )

        return bool(
            getattr(
                state,
                "enabled",
                False,
            )
        )

    try:

        return bool(
            await checker(
                client
            )
        )

    except Exception:

        logger.exception(
            "Unable to check maintenance mode."
        )

        return False


# ============================================================================
# Administrator check
# ============================================================================

async def is_admin(
    client: Client,
    user_id: Optional[int],
) -> bool:

    if user_id is None:
        return False

    try:

        from bot.middleware.auth import (
            is_admin as auth_is_admin,
        )

        return bool(
            await auth_is_admin(
                client,
                int(user_id),
            )
        )

    except Exception:

        logger.exception(
            "Unable to determine admin status."
        )

        return False


# ============================================================================
# Update identity
# ============================================================================

def get_user_id(
    update: Any,
) -> Optional[int]:

    user = getattr(
        update,
        "from_user",
        None,
    )

    if user is None:

        user = getattr(
            update,
            "user",
            None,
        )

    if user is None:
        return None

    try:

        return int(
            user.id
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):

        return None


# ============================================================================
# Access decision
# ============================================================================

async def should_block(
    client: Client,
    update: Any,
) -> bool:
    """
    Return True when this update should be stopped.
    """

    enabled = await maintenance_enabled(
        client
    )

    if not enabled:
        return False

    user_id = get_user_id(
        update
    )

    if user_id is None:

        # Unknown users should not bypass maintenance.
        return True

    # Administrators always bypass maintenance.
    if await is_admin(
        client,
        user_id,
    ):

        return False

    return True


# ============================================================================
# Maintenance UI
# ============================================================================

def state_value(
    state: Any,
    key: str,
    default: Any = None,
) -> Any:

    if state is None:
        return default

    if isinstance(
        state,
        dict,
    ):

        return state.get(
            key,
            default,
        )

    return getattr(
        state,
        key,
        default,
    )


def build_message(
    state: Any,
) -> str:
    """
    Build the user-facing maintenance message.
    """

    message = state_value(
        state,
        "message",
        DEFAULT_MESSAGE,
    )

    if not message:

        message = DEFAULT_MESSAGE

    lines = [
        str(
            message
        )
    ]

    reason = state_value(
        state,
        "reason",
    )

    if reason:

        lines.extend(
            [
                "",
                f"📌 Reason: <b>{escape_html(reason)}</b>",
            ]
        )

    estimated_end = state_value(
        state,
        "estimated_end",
    )

    if estimated_end:

        lines.extend(
            [
                "",
                f"⏰ Expected return: "
                f"<b>{escape_html(estimated_end)}</b>",
            ]
        )

    lines.extend(
        [
            "",
            "🙏 Thank you for your patience.",
        ]
    )

    return "\n".join(
        lines
    )


def build_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Check Again",
                    callback_data=(
                        "maintenance:check"
                    ),
                )
            ]
        ]
    )


# ============================================================================
# Message response
# ============================================================================

async def send_maintenance_message(
    message: Message,
    state: Any,
) -> bool:

    try:

        await message.reply_text(
            build_message(
                state
            ),
            reply_markup=build_keyboard(),
        )

        return True

    except Exception:

        logger.exception(
            "Unable to send maintenance message."
        )

        return False


async def send_maintenance_callback(
    callback_query: CallbackQuery,
    state: Any,
) -> bool:

    try:

        await callback_query.answer(
            "🛠️ Bot is under maintenance.",
            show_alert=True,
        )

    except Exception:

        pass

    message = (
        callback_query.message
    )

    if message is None:
        return False

    try:

        await message.edit_text(
            build_message(
                state
            ),
            reply_markup=build_keyboard(),
        )

        return True

    except Exception:

        logger.exception(
            "Unable to update maintenance callback."
        )

        return False


# ============================================================================
# Middleware class
# ============================================================================

class MaintenanceMiddleware:
    """
    Maintenance middleware.

    Normal flow:

        update
          ↓
        maintenance check
          ↓
        blocked? ── yes ──> maintenance UI
          │
          no
          ↓
        next middleware
    """

    def __init__(
        self,
        *,
        allow_admins: bool = True,
    ) -> None:

        self.allow_admins = bool(
            allow_admins
        )

    async def process(
        self,
        client: Client,
        update: Any,
        context: MiddlewareContext,
        next_handler,
    ):
        """
        Process a Telegram update.
        """

        enabled = await maintenance_enabled(
            client
        )

        state = await get_state(
            client
        )

        context.set(
            MAINTENANCE_CONTEXT_KEY,
            state,
        )

        context.is_maintenance = enabled

        if not enabled:

            return await next_handler()

        user_id = (
            context.user_id
            or get_user_id(
                update
            )
        )

        admin = False

        if (
            self.allow_admins
            and user_id is not None
        ):

            admin = await is_admin(
                client,
                user_id,
            )

        if admin:

            context.is_admin = True

            context.set(
                "maintenance_admin_bypass",
                True,
            )

            return await next_handler()

        context.block(
            "maintenance"
        )

        context.set(
            MAINTENANCE_BLOCKED_KEY,
            True,
        )

        if isinstance(
            update,
            CallbackQuery,
        ):

            await send_maintenance_callback(
                update,
                state,
            )

        elif isinstance(
            update,
            Message,
        ):

            await send_maintenance_message(
                update,
                state,
            )

        return None


# ============================================================================
# Standalone helpers
# ============================================================================

async def require_available(
    client: Client,
    update: Any,
) -> bool:
    """
    Check whether a request may continue.
    """

    if not await should_block(
        client,
        update,
    ):
        return True

    state = await get_state(
        client
    )

    if isinstance(
        update,
        CallbackQuery,
    ):

        await send_maintenance_callback(
            update,
            state,
        )

    elif isinstance(
        update,
        Message,
    ):

        await send_maintenance_message(
            update,
            state,
        )

    return False


def context_is_blocked(
    context: MiddlewareContext,
) -> bool:

    return bool(
        context.get(
            MAINTENANCE_BLOCKED_KEY,
            False,
        )
    )


def context_state(
    context: MiddlewareContext,
) -> Any:

    return context.get(
        MAINTENANCE_CONTEXT_KEY
    )


# ============================================================================
# Callback-specific check
# ============================================================================

async def check_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:
    """
    Check callback access.

    Returns True when callback processing can continue.
    """

    if not await should_block(
        client,
        callback_query,
    ):
        return True

    state = await get_state(
        client
    )

    await send_maintenance_callback(
        callback_query,
        state,
    )

    return False


# ============================================================================
# Message-specific check
# ============================================================================

async def check_message(
    client: Client,
    message: Message,
) -> bool:
    """
    Check message access.

    Returns True when message processing can continue.
    """

    if not await should_block(
        client,
        message,
    ):
        return True

    state = await get_state(
        client
    )

    await send_maintenance_message(
        message,
        state,
    )

    return False


# ============================================================================
# Maintenance bypass
# ============================================================================

async def can_bypass(
    client: Client,
    update: Any,
) -> bool:

    user_id = get_user_id(
        update
    )

    if user_id is None:
        return False

    return await is_admin(
        client,
        user_id,
    )


# ============================================================================
# State invalidation
# ============================================================================

async def refresh(
    client: Client,
):
    """
    Force-refresh maintenance state if supported.
    """

    service = get_maintenance_service()

    if service is None:
        return None

    getter = getattr(
        service,
        "get_maintenance_state",
        None,
    )

    if getter is None:
        return None

    try:

        return await getter(
            client,
            force_refresh=True,
        )

    except TypeError:

        return await getter(
            client
        )

    except Exception:

        logger.exception(
            "Unable to refresh maintenance state."
        )

        return None


# ============================================================================
# Decorator
# ============================================================================

def maintenance_required(
    function,
):
    """
    Decorator for individual handlers.

    Normally the global middleware should handle this. This decorator is
    useful for handlers that may be invoked outside the normal pipeline.
    """

    async def wrapper(
        client: Client,
        update: Any,
        *args,
        **kwargs,
    ):

        if not await require_available(
            client,
            update,
        ):

            return None

        return await function(
            client,
            update,
            *args,
            **kwargs,
        )

    wrapper.__name__ = getattr(
        function,
        "__name__",
        "maintenance_required_handler",
    )

    wrapper.__doc__ = getattr(
        function,
        "__doc__",
        None,
    )

    return wrapper


# ============================================================================
# HTML escaping
# ============================================================================

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
# Registration
# ============================================================================

_default_middleware: Optional[
    MaintenanceMiddleware
] = None


def get_default_middleware(
) -> MaintenanceMiddleware:

    global _default_middleware

    if _default_middleware is None:

        _default_middleware = (
            MaintenanceMiddleware()
        )

    return _default_middleware


def register(
    app: Client,
) -> None:

    global _default_middleware

    _default_middleware = (
        MaintenanceMiddleware()
    )

    logger.info(
        "Maintenance middleware initialized."
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "MaintenanceMiddleware",
    "get_state",
    "maintenance_enabled",
    "should_block",
    "require_available",
    "check_message",
    "check_callback",
    "can_bypass",
    "refresh",
    "context_is_blocked",
    "context_state",
    "maintenance_required",
    "get_default_middleware",
    "register",
]