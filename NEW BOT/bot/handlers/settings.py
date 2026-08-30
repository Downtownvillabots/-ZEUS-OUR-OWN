"""
bot/handlers/settings.py

Group settings handler.

Responsibilities
----------------
- /settings
- Group settings dashboard
- Toggle common group features
- Admin-only access
- Settings navigation

The database/settings service owns persistence.
This module owns Telegram UI and authorization.

Settings covered
----------------
- Auto filter
- IMDB
- Welcome
- Auto delete
- File protection
- Spell check
- PM search
- Verification
- Force subscription
- Custom caption
- Result mode
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Setting definitions
# ============================================================================

SETTING_LABELS = {
    "auto_filter": "🔎 Auto Filter",
    "imdb": "🎬 IMDb",
    "welcome": "👋 Welcome",
    "auto_delete": "🗑️ Auto Delete",
    "file_protection": "🔐 File Protection",
    "spell_check": "✍️ Spell Check",
    "pm_search": "💬 PM Search",
    "verification": "✅ Verification",
    "force_sub": "📢 Force Subscription",
    "custom_caption": "📝 Custom Caption",
    "result_mode": "📋 Result Mode",
}


DEFAULT_SETTINGS = {
    "auto_filter": True,
    "imdb": True,
    "welcome": True,
    "auto_delete": False,
    "file_protection": False,
    "spell_check": True,
    "pm_search": True,
    "verification": False,
    "force_sub": False,
    "custom_caption": False,
    "result_mode": "button",
}


# ============================================================================
# General helpers
# ============================================================================

def escape_html(
    value: Any,
) -> str:
    """
    Escape Telegram HTML.
    """

    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def get_database(
    client: Client,
):
    """
    Get database attached to the application.
    """

    return getattr(
        client,
        "db",
        None,
    )


def is_group(
    chat: Optional[Chat],
) -> bool:

    if chat is None:
        return False

    return chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    )


# ============================================================================
# Group authorization
# ============================================================================

async def is_group_admin(
    client: Client,
    chat_id: int,
    user_id: int,
) -> bool:
    """
    Check whether a user is an administrator in the group.
    """

    try:

        member = await client.get_chat_member(
            chat_id,
            user_id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        logger.exception(
            "Unable to check group admin status "
            "chat=%s user=%s",
            chat_id,
            user_id,
        )

        return False


async def require_group_admin(
    client: Client,
    message: Message,
) -> bool:
    """
    Verify that the command comes from a group administrator.
    """

    if not is_group(
        message.chat
    ):

        await message.reply_text(
            "⚙️ <b>Settings can only be changed inside a group.</b>"
        )

        return False

    user = message.from_user

    if user is None:
        return False

    # Global bot admins always have access.
    try:

        from bot.handlers.admin import (
            is_admin,
        )

        if await is_admin(
            client,
            user.id,
        ):
            return True

    except Exception:
        pass

    if not await is_group_admin(
        client,
        message.chat.id,
        user.id,
    ):

        await message.reply_text(
            "🚫 <b>Only group administrators can change settings.</b>"
        )

        return False

    return True


async def require_group_admin_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:
    """
    Verify callback user is a group administrator.
    """

    message = callback_query.message
    user = callback_query.from_user

    if message is None:
        return False

    if user is None:
        return False

    if not is_group(
        message.chat
    ):

        await callback_query.answer(
            "Settings are available in groups only.",
            show_alert=True,
        )

        return False

    try:

        from bot.handlers.admin import (
            is_admin,
        )

        if await is_admin(
            client,
            user.id,
        ):
            return True

    except Exception:
        pass

    allowed = await is_group_admin(
        client,
        message.chat.id,
        user.id,
    )

    if not allowed:

        await callback_query.answer(
            "🚫 Group administrator access required.",
            show_alert=True,
        )

        return False

    return True


# ============================================================================
# Settings database adapter
# ============================================================================

async def get_settings(
    client: Client,
    chat_id: int,
) -> dict[str, Any]:
    """
    Retrieve settings from database/settings.py.

    Supports the new settings repository while remaining compatible with
    older database APIs.
    """

    db = get_database(
        client
    )

    if db is None:
        return dict(
            DEFAULT_SETTINGS
        )

    # Preferred new API.
    method = getattr(
        db,
        "get_group_settings",
        None,
    )

    if method is not None:

        try:

            result = await method(
                int(chat_id)
            )

            if isinstance(
                result,
                dict,
            ):

                merged = dict(
                    DEFAULT_SETTINGS
                )

                merged.update(
                    result
                )

                return merged

        except Exception:
            logger.exception(
                "get_group_settings failed"
            )

    # Older database API.
    method = getattr(
        db,
        "get_settings",
        None,
    )

    if method is not None:

        try:

            result = await method(
                int(chat_id)
            )

            if isinstance(
                result,
                dict,
            ):

                merged = dict(
                    DEFAULT_SETTINGS
                )

                merged.update(
                    result
                )

                return merged

        except Exception:
            logger.exception(
                "get_settings failed"
            )

    return dict(
        DEFAULT_SETTINGS
    )


async def update_setting(
    client: Client,
    chat_id: int,
    setting: str,
    value: Any,
) -> bool:
    """
    Persist one group setting.
    """

    if setting not in SETTING_LABELS:
        return False

    db = get_database(
        client
    )

    if db is None:
        return False

    # Preferred new API.
    method = getattr(
        db,
        "update_group_setting",
        None,
    )

    if method is not None:

        try:

            result = await method(
                int(chat_id),
                setting,
                value,
            )

            return (
                True
                if result is None
                else bool(result)
            )

        except Exception:
            logger.exception(
                "update_group_setting failed "
                "chat=%s setting=%s",
                chat_id,
                setting,
            )

            return False

    # Generic settings API.
    method = getattr(
        db,
        "update_setting",
        None,
    )

    if method is not None:

        try:

            result = await method(
                int(chat_id),
                setting,
                value,
            )

            return (
                True
                if result is None
                else bool(result)
            )

        except Exception:
            logger.exception(
                "update_setting failed"
            )

            return False

    return False


async def toggle_setting(
    client: Client,
    chat_id: int,
    setting: str,
) -> Optional[bool]:
    """
    Toggle a boolean group setting.
    """

    if setting not in SETTING_LABELS:
        return None

    if setting == "result_mode":
        return None

    settings = await get_settings(
        client,
        chat_id,
    )

    current = bool(
        settings.get(
            setting,
            DEFAULT_SETTINGS.get(
                setting,
                False,
            ),
        )
    )

    new_value = not current

    success = await update_setting(
        client,
        chat_id,
        setting,
        new_value,
    )

    if not success:
        return None

    return new_value


# ============================================================================
# UI
# ============================================================================

def setting_status(
    settings: dict[str, Any],
    name: str,
) -> str:
    """
    Return ON/OFF indicator.
    """

    value = settings.get(
        name
    )

    if value:
        return "✅"

    return "❌"


def build_settings_keyboard(
    settings: dict[str, Any],
) -> InlineKeyboardMarkup:
    """
    Main settings keyboard.
    """

    keyboard = [
        [
            InlineKeyboardButton(
                f"{setting_status(settings, 'auto_filter')} Auto Filter",
                callback_data="settings_toggle:auto_filter",
            ),
            InlineKeyboardButton(
                f"{setting_status(settings, 'imdb')} IMDb",
                callback_data="settings_toggle:imdb",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{setting_status(settings, 'welcome')} Welcome",
                callback_data="settings_toggle:welcome",
            ),
            InlineKeyboardButton(
                f"{setting_status(settings, 'auto_delete')} Auto Delete",
                callback_data="settings_toggle:auto_delete",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{setting_status(settings, 'file_protection')} File Protection",
                callback_data="settings_toggle:file_protection",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{setting_status(settings, 'spell_check')} Spell Check",
                callback_data="settings_toggle:spell_check",
            ),
            InlineKeyboardButton(
                f"{setting_status(settings, 'pm_search')} PM Search",
                callback_data="settings_toggle:pm_search",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{setting_status(settings, 'verification')} Verification",
                callback_data="settings_toggle:verification",
            ),
            InlineKeyboardButton(
                f"{setting_status(settings, 'force_sub')} Force Sub",
                callback_data="settings_toggle:force_sub",
            ),
        ],
        [
            InlineKeyboardButton(
                "📝 Caption",
                callback_data="settings_caption",
            ),
            InlineKeyboardButton(
                "📋 Result Mode",
                callback_data="settings_result_mode",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="settings_refresh",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data="settings_close",
            ),
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def build_settings_text(
    chat: Chat,
    settings: dict[str, Any],
) -> str:
    """
    Format the group settings page.
    """

    title = (
        chat.title
        or "This Group"
    )

    result_mode = settings.get(
        "result_mode",
        "button",
    )

    return (
        "<b>⚙️ Group Settings</b>\n\n"
        f"👥 Group: <b>{escape_html(title)}</b>\n"
        f"🆔 ID: <code>{chat.id}</code>\n\n"
        "<b>Features</b>\n\n"
        f"{setting_status(settings, 'auto_filter')} Auto Filter\n"
        f"{setting_status(settings, 'imdb')} IMDb\n"
        f"{setting_status(settings, 'welcome')} Welcome\n"
        f"{setting_status(settings, 'auto_delete')} Auto Delete\n"
        f"{setting_status(settings, 'file_protection')} File Protection\n"
        f"{setting_status(settings, 'spell_check')} Spell Check\n"
        f"{setting_status(settings, 'pm_search')} PM Search\n"
        f"{setting_status(settings, 'verification')} Verification\n"
        f"{setting_status(settings, 'force_sub')} Force Subscription\n"
        "\n"
        f"📋 Result mode: <b>{escape_html(result_mode)}</b>\n\n"
        "<i>Only group administrators can modify these settings.</i>"
    )


# ============================================================================
# /settings
# ============================================================================

async def settings_command(
    client: Client,
    message: Message,
):
    """
    Open group settings.
    """

    if not await require_group_admin(
        client,
        message,
    ):
        return

    settings = await get_settings(
        client,
        message.chat.id,
    )

    await message.reply_text(
        build_settings_text(
            message.chat,
            settings,
        ),
        reply_markup=build_settings_keyboard(
            settings
        ),
    )


# ============================================================================
# Toggle callback
# ============================================================================

async def settings_toggle_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Toggle one boolean setting.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = "settings_toggle:"

    if not data.startswith(
        prefix
    ):
        return

    setting = data[
        len(prefix):
    ]

    if setting not in SETTING_LABELS:
        await callback_query.answer(
            "Unknown setting.",
            show_alert=True,
        )
        return

    message = (
        callback_query.message
    )

    if message is None:
        return

    new_value = await toggle_setting(
        client,
        message.chat.id,
        setting,
    )

    if new_value is None:

        await callback_query.answer(
            "Unable to update this setting.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        (
            f"{SETTING_LABELS[setting]} "
            f"{'enabled' if new_value else 'disabled'}."
        )
    )

    settings = await get_settings(
        client,
        message.chat.id,
    )

    try:

        await message.edit_text(
            build_settings_text(
                message.chat,
                settings,
            ),
            reply_markup=build_settings_keyboard(
                settings
            ),
        )

    except Exception:
        logger.exception(
            "Unable to refresh settings UI"
        )


# ============================================================================
# Refresh
# ============================================================================

async def settings_refresh_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Refresh settings page.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer(
        "Refreshing..."
    )

    message = (
        callback_query.message
    )

    if message is None:
        return

    settings = await get_settings(
        client,
        message.chat.id,
    )

    try:

        await message.edit_text(
            build_settings_text(
                message.chat,
                settings,
            ),
            reply_markup=build_settings_keyboard(
                settings
            ),
        )

    except Exception:
        logger.exception(
            "Unable to refresh settings"
        )


# ============================================================================
# Caption settings
# ============================================================================

def build_caption_keyboard(
    enabled: bool,
) -> InlineKeyboardMarkup:
    """
    Caption settings menu.
    """

    state = (
        "Disable"
        if enabled
        else "Enable"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"📝 {state} Caption",
                    callback_data="settings_caption_toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Set Caption",
                    callback_data="settings_caption_set",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="settings_refresh",
                )
            ],
        ]
    )


async def caption_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Display caption settings.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

    message = (
        callback_query.message
    )

    if message is None:
        return

    settings = await get_settings(
        client,
        message.chat.id,
    )

    enabled = bool(
        settings.get(
            "custom_caption",
            False,
        )
    )

    caption = settings.get(
        "caption",
        "",
    )

    text = (
        "<b>📝 Custom Caption</b>\n\n"
        f"Status: "
        f"<b>{'Enabled' if enabled else 'Disabled'}</b>\n\n"
        f"Current caption:\n"
        f"<code>{escape_html(caption or 'Not configured')}</code>\n\n"
        "<i>Use the button below to configure the caption.</i>"
    )

    await message.edit_text(
        text,
        reply_markup=build_caption_keyboard(
            enabled
        ),
    )


async def caption_toggle_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Toggle custom caption.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    message = (
        callback_query.message
    )

    if message is None:
        return

    new_value = await toggle_setting(
        client,
        message.chat.id,
        "custom_caption",
    )

    if new_value is None:

        await callback_query.answer(
            "Unable to change caption setting.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        (
            "Custom caption enabled."
            if new_value
            else
            "Custom caption disabled."
        )
    )

    await caption_callback(
        client,
        callback_query,
    )


async def caption_set_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Start caption configuration.

    We use a state manager when available. The actual message capture
    will be implemented in the settings conversation handler later.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

    message = (
        callback_query.message
    )

    if message is None:
        return

    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is not None:

        setter = getattr(
            state_manager,
            "set",
            None,
        )

        if setter:

            try:

                await setter(
                    callback_query.from_user.id,
                    {
                        "state": "settings_caption",
                        "chat_id": message.chat.id,
                    },
                )

            except Exception:
                logger.exception(
                    "Unable to store caption state"
                )

    await message.edit_text(
        "<b>📝 Set Custom Caption</b>\n\n"
        "Send the caption as your next message.\n\n"
        "<b>Available placeholders:</b>\n"
        "<code>{file_name}</code>\n"
        "<code>{file_size}</code>\n"
        "<code>{caption}</code>\n\n"
        "Use /cancel to stop.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="settings_refresh",
                    )
                ]
            ]
        ),
    )


# ============================================================================
# Result mode
# ============================================================================

RESULT_MODES = {
    "button": "Buttons",
    "text": "Text List",
}


def build_result_mode_keyboard(
    current: str,
) -> InlineKeyboardMarkup:
    """
    Result mode selector.
    """

    rows = []

    for mode, label in RESULT_MODES.items():

        prefix = (
            "✅ "
            if mode == current
            else ""
        )

        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix}{label}",
                    callback_data=(
                        f"settings_result:{mode}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="settings_refresh",
            )
        ]
    )

    return InlineKeyboardMarkup(
        rows
    )


async def result_mode_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Display result mode options.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

    message = (
        callback_query.message
    )

    if message is None:
        return

    settings = await get_settings(
        client,
        message.chat.id,
    )

    current = str(
        settings.get(
            "result_mode",
            "button",
        )
    )

    await message.edit_text(
        "<b>📋 Result Mode</b>\n\n"
        "Choose how search results should be displayed.",
        reply_markup=build_result_mode_keyboard(
            current
        ),
    )


async def result_mode_select_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Save selected result mode.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = "settings_result:"

    if not data.startswith(
        prefix
    ):
        return

    mode = data[
        len(prefix):
    ]

    if mode not in RESULT_MODES:

        await callback_query.answer(
            "Invalid result mode.",
            show_alert=True,
        )

        return

    message = (
        callback_query.message
    )

    if message is None:
        return

    success = await update_setting(
        client,
        message.chat.id,
        "result_mode",
        mode,
    )

    if not success:

        await callback_query.answer(
            "Unable to save result mode.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        f"Result mode: {RESULT_MODES[mode]}"
    )

    settings = await get_settings(
        client,
        message.chat.id,
    )

    await message.edit_text(
        build_settings_text(
            message.chat,
            settings,
        ),
        reply_markup=build_settings_keyboard(
            settings
        ),
    )


# ============================================================================
# Close
# ============================================================================

async def settings_close_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Close settings message.
    """

    if not await require_group_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

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
# Registration
# ============================================================================

def register(
    app: Client,
):
    """
    Register group settings handlers.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    # /settings
    app.add_handler(
        MessageHandler(
            settings_command,
            filters.command(
                "settings"
            ),
        )
    )

    # Toggle.
    app.add_handler(
        CallbackQueryHandler(
            settings_toggle_callback,
            filters.regex(
                r"^settings_toggle:"
            ),
        )
    )

    # Refresh.
    app.add_handler(
        CallbackQueryHandler(
            settings_refresh_callback,
            filters.regex(
                r"^settings_refresh$"
            ),
        )
    )

    # Caption.
    app.add_handler(
        CallbackQueryHandler(
            caption_callback,
            filters.regex(
                r"^settings_caption$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            caption_toggle_callback,
            filters.regex(
                r"^settings_caption_toggle$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            caption_set_callback,
            filters.regex(
                r"^settings_caption_set$"
            ),
        )
    )

    # Result mode.
    app.add_handler(
        CallbackQueryHandler(
            result_mode_callback,
            filters.regex(
                r"^settings_result_mode$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            result_mode_select_callback,
            filters.regex(
                r"^settings_result:"
            ),
        )
    )

    # Close.
    app.add_handler(
        CallbackQueryHandler(
            settings_close_callback,
            filters.regex(
                r"^settings_close$"
            ),
        )
    )

    logger.info(
        "Registered settings handlers"
    )


# ============================================================================
# Plugin handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "settings"
    )
)
async def settings_handler(
    client: Client,
    message: Message,
):
    await settings_command(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_toggle:"
    )
)
async def settings_toggle_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await settings_toggle_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_refresh$"
    )
)
async def settings_refresh_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await settings_refresh_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_caption$"
    )
)
async def settings_caption_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await caption_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_caption_toggle$"
    )
)
async def settings_caption_toggle_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await caption_toggle_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_caption_set$"
    )
)
async def settings_caption_set_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await caption_set_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_result_mode$"
    )
)
async def settings_result_mode_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await result_mode_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_result:"
    )
)
async def settings_result_select_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await result_mode_select_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^settings_close$"
    )
)
async def settings_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await settings_close_callback(
        client,
        callback_query,
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "settings_command",
    "settings_handler",
    "settings_toggle_callback",
    "settings_refresh_callback",
    "caption_callback",
    "caption_toggle_callback",
    "caption_set_callback",
    "result_mode_callback",
    "result_mode_select_callback",
    "settings_close_callback",
    "get_settings",
    "update_setting",
    "toggle_setting",
    "build_settings_keyboard",
    "build_settings_text",
    "register",
]