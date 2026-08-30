"""
bot/handlers/maintenance.py

Global maintenance-mode handler.

Responsibilities
----------------
- Enable maintenance mode
- Disable maintenance mode
- Show maintenance status
- Admin bypass
- User-facing maintenance message
- Persistent maintenance state
- Maintenance callbacks
- Optional maintenance reason/message
- Optional estimated return time

Commands
--------
/maintenance
/maintenance_on
/maintenance_off
/maintenance_status

Examples
--------
/maintenance on
/maintenance off
/maintenance status

/maintenance on Database maintenance
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

MAINTENANCE_STATE_KEY = "bot:maintenance"

MAINTENANCE_ENABLED = "enabled"

MAINTENANCE_DISABLED = "disabled"

DEFAULT_MAINTENANCE_MESSAGE = (
    "🛠️ <b>Bot Under Maintenance</b>\n\n"
    "We're currently performing maintenance.\n"
    "Please try again later."
)

MAINTENANCE_CALLBACK_PREFIX = "maintenance"

COMMAND_ALIASES = {
    "on",
    "enable",
    "enabled",
    "start",
    "1",
    "true",
}

DISABLE_ALIASES = {
    "off",
    "disable",
    "disabled",
    "stop",
    "0",
    "false",
}

STATUS_ALIASES = {
    "status",
    "info",
    "check",
}


# ============================================================================
# Data model
# ============================================================================

@dataclass
class MaintenanceState:
    """
    Runtime representation of maintenance mode.
    """

    enabled: bool = False

    message: str = DEFAULT_MAINTENANCE_MESSAGE

    reason: Optional[str] = None

    enabled_by: Optional[int] = None

    enabled_at: Optional[float] = None

    estimated_end: Optional[str] = None

    version: int = 1

    def to_dict(self) -> dict[str, Any]:

        return {
            "enabled": self.enabled,
            "message": self.message,
            "reason": self.reason,
            "enabled_by": self.enabled_by,
            "enabled_at": self.enabled_at,
            "estimated_end": self.estimated_end,
            "version": self.version,
        }

    @classmethod
    def from_value(
        cls,
        value: Any,
    ) -> "MaintenanceState":

        if isinstance(
            value,
            cls,
        ):
            return value

        if not isinstance(
            value,
            dict,
        ):
            return cls()

        return cls(
            enabled=bool(
                value.get(
                    "enabled",
                    False,
                )
            ),
            message=str(
                value.get(
                    "message",
                    DEFAULT_MAINTENANCE_MESSAGE,
                )
                or DEFAULT_MAINTENANCE_MESSAGE
            ),
            reason=value.get(
                "reason"
            ),
            enabled_by=value.get(
                "enabled_by"
            ),
            enabled_at=value.get(
                "enabled_at"
            ),
            estimated_end=value.get(
                "estimated_end"
            ),
            version=int(
                value.get(
                    "version",
                    1,
                )
            ),
        )


# ============================================================================
# Runtime cache
# ============================================================================

_cached_state: Optional[
    MaintenanceState
] = None

_cached_at: float = 0.0

CACHE_TTL = 5.0


# ============================================================================
# Generic helpers
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


def get_database(
    client: Client,
):

    return getattr(
        client,
        "db",
        None,
    )


def get_state_manager(
    client: Client,
):

    return getattr(
        client,
        "state_manager",
        None,
    )


async def call_method(
    obj: Any,
    names: tuple[str, ...],
    *args,
    **kwargs,
):
    """
    Call first available method.

    Returns:
        found, result
    """

    if obj is None:
        return False, None

    for name in names:

        method = getattr(
            obj,
            name,
            None,
        )

        if method is None:
            continue

        try:

            result = method(
                *args,
                **kwargs,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return True, result

        except Exception:

            logger.exception(
                "Method failed: %s",
                name,
            )

            return True, None

    return False, None


# ============================================================================
# State manager persistence
# ============================================================================

async def load_from_state_manager(
    client: Client,
) -> Optional[MaintenanceState]:

    state_manager = get_state_manager(
        client
    )

    if state_manager is None:
        return None

    found, result = await call_method(
        state_manager,
        (
            "get",
            "get_state",
            "load",
        ),
        MAINTENANCE_STATE_KEY,
    )

    if not found:
        return None

    if result is None:
        return None

    return MaintenanceState.from_value(
        result
    )


async def save_to_state_manager(
    client: Client,
    state: MaintenanceState,
) -> bool:

    state_manager = get_state_manager(
        client
    )

    if state_manager is None:
        return False

    payload = state.to_dict()

    found, result = await call_method(
        state_manager,
        (
            "set",
            "set_state",
            "save",
        ),
        MAINTENANCE_STATE_KEY,
        payload,
    )

    if not found:
        return False

    return result is not False


async def clear_state_manager(
    client: Client,
) -> bool:

    state_manager = get_state_manager(
        client
    )

    if state_manager is None:
        return False

    found, result = await call_method(
        state_manager,
        (
            "delete",
            "remove",
            "clear",
        ),
        MAINTENANCE_STATE_KEY,
    )

    if not found:
        return False

    return result is not False


# ============================================================================
# Database persistence
# ============================================================================

async def load_from_database(
    client: Client,
) -> Optional[MaintenanceState]:

    db = get_database(
        client
    )

    if db is None:
        return None

    found, result = await call_method(
        db,
        (
            "get_maintenance",
            "get_maintenance_state",
            "get_bot_setting",
            "get_setting",
        ),
        MAINTENANCE_STATE_KEY,
    )

    if found and result is not None:

        if isinstance(
            result,
            dict,
        ):

            # Some database APIs return:
            #
            # {
            #   "key": "...",
            #   "value": {...}
            # }
            #
            # Handle that shape as well.

            if "value" in result:

                result = result[
                    "value"
                ]

        return MaintenanceState.from_value(
            result
        )

    return None


async def save_to_database(
    client: Client,
    state: MaintenanceState,
) -> bool:

    db = get_database(
        client
    )

    if db is None:
        return False

    payload = state.to_dict()

    found, result = await call_method(
        db,
        (
            "set_maintenance",
            "save_maintenance",
            "update_maintenance",
            "set_maintenance_state",
        ),
        payload,
    )

    if found:
        return result is not False

    # Generic settings fallback.
    found, result = await call_method(
        db,
        (
            "set_bot_setting",
            "set_setting",
            "update_setting",
        ),
        MAINTENANCE_STATE_KEY,
        payload,
    )

    if found:
        return result is not False

    return False


# ============================================================================
# State loading
# ============================================================================

async def get_maintenance_state(
    client: Client,
    *,
    force_refresh: bool = False,
) -> MaintenanceState:
    """
    Get current maintenance state.

    A very small cache avoids hitting the database on every incoming
    message while still allowing changes to propagate quickly.
    """

    global _cached_state
    global _cached_at

    now = time.monotonic()

    if (
        not force_refresh
        and _cached_state is not None
        and (
            now - _cached_at
        ) < CACHE_TTL
    ):

        return _cached_state

    state = await load_from_state_manager(
        client
    )

    if state is None:

        state = await load_from_database(
            client
        )

    if state is None:

        state = MaintenanceState()

    _cached_state = state

    _cached_at = now

    return state


# ============================================================================
# State saving
# ============================================================================

async def set_maintenance_state(
    client: Client,
    state: MaintenanceState,
) -> bool:

    global _cached_state
    global _cached_at

    state.version += 1

    state_saved = False

    # Prefer state manager.
    try:

        state_saved = await save_to_state_manager(
            client,
            state,
        )

    except Exception:

        logger.exception(
            "Unable to save maintenance state using state manager"
        )

    # Database remains a persistent fallback.
    try:

        db_saved = await save_to_database(
            client,
            state,
        )

        state_saved = (
            state_saved
            or db_saved
        )

    except Exception:

        logger.exception(
            "Unable to save maintenance state using database"
        )

    _cached_state = state

    _cached_at = time.monotonic()

    return state_saved


# ============================================================================
# Enabled state
# ============================================================================

async def is_maintenance_mode(
    client: Client,
) -> bool:

    state = await get_maintenance_state(
        client
    )

    return bool(
        state.enabled
    )


async def enable_maintenance(
    client: Client,
    *,
    admin_id: Optional[int] = None,
    message: Optional[str] = None,
    reason: Optional[str] = None,
    estimated_end: Optional[str] = None,
) -> MaintenanceState:
    """
    Enable maintenance mode.
    """

    state = await get_maintenance_state(
        client,
        force_refresh=True,
    )

    state.enabled = True

    state.enabled_by = (
        int(admin_id)
        if admin_id is not None
        else state.enabled_by
    )

    state.enabled_at = (
        time.time()
    )

    if message:

        state.message = str(
            message
        ).strip()

    elif not state.message:

        state.message = (
            DEFAULT_MAINTENANCE_MESSAGE
        )

    state.reason = (
        str(reason).strip()
        if reason
        else None
    )

    state.estimated_end = (
        str(
            estimated_end
        ).strip()
        if estimated_end
        else None
    )

    await set_maintenance_state(
        client,
        state,
    )

    logger.warning(
        "Maintenance mode enabled by %s",
        admin_id,
    )

    return state


async def disable_maintenance(
    client: Client,
) -> MaintenanceState:
    """
    Disable maintenance mode.
    """

    state = await get_maintenance_state(
        client,
        force_refresh=True,
    )

    state.enabled = False

    state.reason = None

    state.estimated_end = None

    await set_maintenance_state(
        client,
        state,
    )

    logger.info(
        "Maintenance mode disabled"
    )

    return state


# ============================================================================
# Admin detection
# ============================================================================

async def is_admin(
    client: Client,
    user_id: int,
) -> bool:

    try:

        from bot.handlers.admin import (
            is_admin as admin_check,
        )

        return bool(
            await admin_check(
                client,
                int(user_id),
            )
        )

    except Exception:

        logger.exception(
            "Unable to check administrator status"
        )

        return False


# ============================================================================
# Maintenance message
# ============================================================================

def build_maintenance_message(
    state: MaintenanceState,
) -> str:

    lines = [
        state.message
        or DEFAULT_MAINTENANCE_MESSAGE,
    ]

    if state.reason:

        lines.extend(
            [
                "",
                f"📌 Reason: "
                f"<b>{escape_html(state.reason)}</b>",
            ]
        )

    if state.estimated_end:

        lines.extend(
            [
                "",
                f"⏰ Expected return: "
                f"<b>{escape_html(state.estimated_end)}</b>",
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


# ============================================================================
# Maintenance gate
# ============================================================================

async def check_maintenance(
    client: Client,
    user_id: Optional[int],
) -> bool:
    """
    Return True when the request should be blocked.

    Administrators always bypass maintenance mode.
    """

    state = await get_maintenance_state(
        client
    )

    if not state.enabled:
        return False

    if user_id is None:
        return True

    if await is_admin(
        client,
        int(user_id),
    ):
        return False

    return True


async def maintenance_gate(
    client: Client,
    message: Message,
) -> bool:
    """
    Handler helper.

    Returns:
        True  -> continue processing
        False -> maintenance response was shown
    """

    user = message.from_user

    user_id = (
        int(user.id)
        if user
        else None
    )

    blocked = await check_maintenance(
        client,
        user_id,
    )

    if not blocked:
        return True

    state = await get_maintenance_state(
        client
    )

    await message.reply_text(
        build_maintenance_message(
            state
        )
    )

    return False


async def maintenance_callback_gate(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:

    user = callback_query.from_user

    user_id = (
        int(user.id)
        if user
        else None
    )

    blocked = await check_maintenance(
        client,
        user_id,
    )

    if not blocked:
        return True

    state = await get_maintenance_state(
        client
    )

    await callback_query.answer(
        "🛠️ Bot is currently under maintenance.",
        show_alert=True,
    )

    if callback_query.message:

        try:

            await callback_query.message.edit_text(
                build_maintenance_message(
                    state
                )
            )

        except Exception:
            pass

    return False


# ============================================================================
# Maintenance status text
# ============================================================================

def format_timestamp(
    timestamp: Optional[float],
) -> str:

    if not timestamp:
        return "Unknown"

    try:

        return datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ).strftime(
            "%d %b %Y, %H:%M UTC"
        )

    except (
        ValueError,
        OverflowError,
        OSError,
    ):

        return "Unknown"


def build_status_text(
    state: MaintenanceState,
) -> str:

    status = (
        "🟢 OFF"
        if not state.enabled
        else "🔴 ON"
    )

    lines = [
        "<b>🛠️ Maintenance Status</b>",
        "",
        f"Status: <b>{status}</b>",
    ]

    if state.enabled:

        lines.extend(
            [
                f"Enabled at: "
                f"<b>{escape_html(format_timestamp(state.enabled_at))}</b>",
            ]
        )

        if state.enabled_by:

            lines.append(
                f"Enabled by: "
                f"<code>{state.enabled_by}</code>"
            )

        if state.reason:

            lines.append(
                f"Reason: "
                f"<b>{escape_html(state.reason)}</b>"
            )

        if state.estimated_end:

            lines.append(
                f"Expected return: "
                f"<b>{escape_html(state.estimated_end)}</b>"
            )

    else:

        lines.append(
            "Users can access the bot normally."
        )

    return "\n".join(
        lines
    )


# ============================================================================
# Admin keyboard
# ============================================================================

def build_admin_maintenance_keyboard(
    enabled: bool,
) -> InlineKeyboardMarkup:

    toggle_text = (
        "🟢 Disable Maintenance"
        if enabled
        else "🔴 Enable Maintenance"
    )

    toggle_callback = (
        "maintenance:disable"
        if enabled
        else "maintenance:enable"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    toggle_text,
                    callback_data=toggle_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Refresh",
                    callback_data=(
                        "maintenance:status"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=(
                        "maintenance:close"
                    ),
                )
            ],
        ]
    )


# ============================================================================
# /maintenance
# ============================================================================

async def maintenance_command(
    client: Client,
    message: Message,
):
    """
    Main maintenance command.

    Supported:

        /maintenance
        /maintenance status
        /maintenance on
        /maintenance off

        /maintenance on Database maintenance
    """

    if not await require_admin(
        client,
        message,
    ):
        return

    command = (
        message.command
        or []
    )

    if len(command) == 1:

        await show_maintenance_panel(
            client,
            message,
        )

        return

    action = str(
        command[1]
    ).strip().lower()

    if action in STATUS_ALIASES:

        await show_maintenance_panel(
            client,
            message,
        )

        return

    if action in COMMAND_ALIASES:

        reason = None

        if len(command) > 2:

            reason = " ".join(
                command[2:]
            ).strip()

        await enable_maintenance(
            client,
            admin_id=(
                message.from_user.id
                if message.from_user
                else None
            ),
            reason=reason,
        )

        await message.reply_text(
            "<b>🔴 Maintenance Enabled</b>\n\n"
            "Normal users will now see the maintenance screen.\n"
            "Administrators can continue using the bot."
        )

        return

    if action in DISABLE_ALIASES:

        await disable_maintenance(
            client
        )

        await message.reply_text(
            "<b>🟢 Maintenance Disabled</b>\n\n"
            "The bot is available to users again."
        )

        return

    await message.reply_text(
        "<b>🛠️ Maintenance</b>\n\n"
        "Usage:\n\n"
        "<code>/maintenance</code>\n"
        "<code>/maintenance on</code>\n"
        "<code>/maintenance off</code>\n"
        "<code>/maintenance status</code>\n\n"
        "Optional reason:\n"
        "<code>/maintenance on Database maintenance</code>"
    )


# ============================================================================
# /maintenance_on
# ============================================================================

async def maintenance_on_command(
    client: Client,
    message: Message,
):

    if not await require_admin(
        client,
        message,
    ):
        return

    command = (
        message.command
        or []
    )

    reason = None

    if len(command) > 1:

        reason = " ".join(
            command[1:]
        ).strip()

    state = await enable_maintenance(
        client,
        admin_id=(
            message.from_user.id
            if message.from_user
            else None
        ),
        reason=reason,
    )

    await message.reply_text(
        build_status_text(
            state
        ),
        reply_markup=build_admin_maintenance_keyboard(
            True
        ),
    )


# ============================================================================
# /maintenance_off
# ============================================================================

async def maintenance_off_command(
    client: Client,
    message: Message,
):

    if not await require_admin(
        client,
        message,
    ):
        return

    state = await disable_maintenance(
        client
    )

    await message.reply_text(
        build_status_text(
            state
        ),
        reply_markup=build_admin_maintenance_keyboard(
            False
        ),
    )


# ============================================================================
# /maintenance_status
# ============================================================================

async def maintenance_status_command(
    client: Client,
    message: Message,
):

    if not await require_admin(
        client,
        message,
    ):
        return

    await show_maintenance_panel(
        client,
        message,
    )


# ============================================================================
# Maintenance panel
# ============================================================================

async def show_maintenance_panel(
    client: Client,
    message: Message,
):

    state = await get_maintenance_state(
        client,
        force_refresh=True,
    )

    await message.reply_text(
        build_status_text(
            state
        ),
        reply_markup=build_admin_maintenance_keyboard(
            state.enabled
        ),
    )


# ============================================================================
# Enable callback
# ============================================================================

async def enable_callback(
    client: Client,
    callback_query: CallbackQuery,
):

    user = callback_query.from_user

    if user is None:
        return

    if not await is_admin(
        client,
        int(user.id),
    ):

        await callback_query.answer(
            "🚫 Administrator access required.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "🔴 Maintenance enabled."
    )

    state = await enable_maintenance(
        client,
        admin_id=int(
            user.id
        ),
    )

    if callback_query.message:

        try:

            await callback_query.message.edit_text(
                build_status_text(
                    state
                ),
                reply_markup=build_admin_maintenance_keyboard(
                    True
                ),
            )

        except Exception:

            logger.exception(
                "Unable to update maintenance panel"
            )


# ============================================================================
# Disable callback
# ============================================================================

async def disable_callback(
    client: Client,
    callback_query: CallbackQuery,
):

    user = callback_query.from_user

    if user is None:
        return

    if not await is_admin(
        client,
        int(user.id),
    ):

        await callback_query.answer(
            "🚫 Administrator access required.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "🟢 Maintenance disabled."
    )

    state = await disable_maintenance(
        client
    )

    if callback_query.message:

        try:

            await callback_query.message.edit_text(
                build_status_text(
                    state
                ),
                reply_markup=build_admin_maintenance_keyboard(
                    False
                ),
            )

        except Exception:

            logger.exception(
                "Unable to update maintenance panel"
            )


# ============================================================================
# Status callback
# ============================================================================

async def status_callback(
    client: Client,
    callback_query: CallbackQuery,
):

    user = callback_query.from_user

    if user is None:
        return

    if not await is_admin(
        client,
        int(user.id),
    ):

        await callback_query.answer(
            "🚫 Administrator access required.",
            show_alert=True,
        )

        return

    state = await get_maintenance_state(
        client,
        force_refresh=True,
    )

    await callback_query.answer(
        "🔄 Refreshed."
    )

    if callback_query.message:

        try:

            await callback_query.message.edit_text(
                build_status_text(
                    state
                ),
                reply_markup=build_admin_maintenance_keyboard(
                    state.enabled
                ),
            )

        except Exception:

            logger.exception(
                "Unable to refresh maintenance panel"
            )


# ============================================================================
# Close callback
# ============================================================================

async def close_callback(
    client: Client,
    callback_query: CallbackQuery,
):

    user = callback_query.from_user

    if user is None:
        return

    if not await is_admin(
        client,
        int(user.id),
    ):

        await callback_query.answer(
            "🚫 Administrator access required.",
            show_alert=True,
        )

        return

    await callback_query.answer()

    if callback_query.message:

        try:

            await callback_query.message.delete()

        except Exception:

            try:

                await callback_query.message.edit_reply_markup(
                    reply_markup=None
                )

            except Exception:
                pass


# ============================================================================
# Require admin helper
# ============================================================================

async def require_admin(
    client: Client,
    message: Message,
) -> bool:

    user = message.from_user

    if user is None:
        return False

    if await is_admin(
        client,
        int(user.id),
    ):
        return True

    await message.reply_text(
        "🚫 <b>Administrator access required.</b>"
    )

    return False


# ============================================================================
# Middleware-style helper
# ============================================================================

async def should_process_message(
    client: Client,
    message: Message,
) -> bool:
    """
    Generic middleware helper.

    Use this at the top of normal user handlers:

        if not await should_process_message(client, message):
            return

    Admins always pass.
    """

    user = message.from_user

    if user is None:
        return False

    return not await check_maintenance(
        client,
        int(user.id),
    )


# ============================================================================
# Callback middleware helper
# ============================================================================

async def should_process_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:
    """
    Generic callback middleware helper.
    """

    user = callback_query.from_user

    if user is None:
        return False

    return not await check_maintenance(
        client,
        int(user.id),
    )


# ============================================================================
# Plugin handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "maintenance"
    )
)
async def maintenance_handler(
    client: Client,
    message: Message,
):
    await maintenance_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "maintenance_on"
    )
)
async def maintenance_on_handler(
    client: Client,
    message: Message,
):
    await maintenance_on_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "maintenance_off"
    )
)
async def maintenance_off_handler(
    client: Client,
    message: Message,
):
    await maintenance_off_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "maintenance_status"
    )
)
async def maintenance_status_handler(
    client: Client,
    message: Message,
):
    await maintenance_status_command(
        client,
        message,
    )


# ============================================================================
# Callback handlers
# ============================================================================

@Client.on_callback_query(
    filters.regex(
        r"^maintenance:enable$"
    )
)
async def maintenance_enable_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await enable_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^maintenance:disable$"
    )
)
async def maintenance_disable_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await disable_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^maintenance:status$"
    )
)
async def maintenance_status_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await status_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^maintenance:close$"
    )
)
async def maintenance_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await close_callback(
        client,
        callback_query,
    )


# ============================================================================
# Explicit registration
# ============================================================================

def register(
    app: Client,
):
    """
    Explicit handler registration.

    Use this OR Pyrogram plugin discovery, not both.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    app.add_handler(
        MessageHandler(
            maintenance_handler,
            filters.command(
                "maintenance"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            maintenance_on_handler,
            filters.command(
                "maintenance_on"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            maintenance_off_handler,
            filters.command(
                "maintenance_off"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            maintenance_status_handler,
            filters.command(
                "maintenance_status"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            maintenance_enable_handler,
            filters.regex(
                r"^maintenance:enable$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            maintenance_disable_handler,
            filters.regex(
                r"^maintenance:disable$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            maintenance_status_callback_handler,
            filters.regex(
                r"^maintenance:status$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            maintenance_close_handler,
            filters.regex(
                r"^maintenance:close$"
            ),
        )
    )

    logger.info(
        "Registered maintenance handlers"
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "MaintenanceState",
    "get_maintenance_state",
    "set_maintenance_state",
    "is_maintenance_mode",
    "enable_maintenance",
    "disable_maintenance",
    "check_maintenance",
    "maintenance_gate",
    "maintenance_callback_gate",
    "should_process_message",
    "should_process_callback",
    "build_maintenance_message",
    "build_status_text",
    "maintenance_command",
    "maintenance_on_command",
    "maintenance_off_command",
    "maintenance_status_command",
    "register",
]