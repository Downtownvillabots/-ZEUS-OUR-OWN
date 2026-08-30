"""
bot/handlers/user.py

Common user-facing Telegram handlers.

Responsibilities:
    - /help
    - /about
    - /id
    - /me
    - /status
    - /cancel
    - Main menu callbacks
    - Basic user information

Business logic remains in services/database modules.
"""

from __future__ import annotations

import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Text
# ============================================================================

HELP_TEXT = """
<b>📚 Help & Commands</b>

━━━━━━━━━━━━━━━━━━━━

<b>🔎 Search</b>

Simply send me the name of a movie, series, or file.

Example:
<code>Avengers Endgame</code>

You can also include details:

<code>Avengers Endgame 2019</code>
<code>Breaking Bad S01</code>
<code>Avatar 1080p</code>

━━━━━━━━━━━━━━━━━━━━

<b>👤 User Commands</b>

<code>/start</code> — Start the bot
<code>/help</code> — Show this help
<code>/id</code> — Show your Telegram ID
<code>/me</code> — Show your account
<code>/status</code> — Show account status
<code>/cancel</code> — Cancel current operation

━━━━━━━━━━━━━━━━━━━━

<b>📂 File Search</b>

Send any movie or file name and the bot will search
the available database.

━━━━━━━━━━━━━━━━━━━━

<b>🔐 Verification</b>

Some files may require verification before they can
be accessed.

━━━━━━━━━━━━━━━━━━━━

<i>Choose an option below or send a search query.</i>
"""


ABOUT_TEXT = """
<b>🎬 About {bot_name}</b>

━━━━━━━━━━━━━━━━━━━━

A fast Telegram movie and file search bot.

<b>Features</b>

🔎 Smart file search
🎬 Movie information
📂 File delivery
🔐 Verification system
⚡ Fast results
👤 User accounts
⭐ Premium support
🛠️ Group settings

━━━━━━━━━━━━━━━━━━━━

<i>Built with Pyrofork and MongoDB.</i>
"""


# ============================================================================
# Keyboard builders
# ============================================================================

def build_help_keyboard() -> InlineKeyboardMarkup:
    """
    Help menu keyboard.
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search",
                    callback_data="menu_search",
                ),
            ],
            [
                InlineKeyboardButton(
                    "👤 My Account",
                    callback_data="user_profile",
                ),
                InlineKeyboardButton(
                    "⭐ Premium",
                    callback_data="user_premium",
                ),
            ],
            [
                InlineKeyboardButton(
                    "ℹ️ About",
                    callback_data="menu_about",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="user_close",
                ),
            ],
        ]
    )


def build_profile_keyboard() -> InlineKeyboardMarkup:
    """
    User profile keyboard.
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ Premium",
                    callback_data="user_premium",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔎 Search",
                    callback_data="menu_search",
                ),
                InlineKeyboardButton(
                    "📚 Help",
                    callback_data="menu_help",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="user_close",
                ),
            ],
        ]
    )


def build_about_keyboard() -> InlineKeyboardMarkup:
    """
    About keyboard.
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📚 Help",
                    callback_data="menu_help",
                ),
                InlineKeyboardButton(
                    "🔎 Search",
                    callback_data="menu_search",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="user_close",
                ),
            ],
        ]
    )


# ============================================================================
# Helpers
# ============================================================================

def get_bot_name(
    client: Client,
) -> str:
    """
    Get bot's display name.
    """

    me = getattr(
        client,
        "me",
        None,
    )

    if me:

        name = getattr(
            me,
            "first_name",
            None,
        )

        if name:
            return str(name)

        username = getattr(
            me,
            "username",
            None,
        )

        if username:
            return f"@{username}"

    return "Movie Bot"


def escape_html(
    value: object,
) -> str:
    """
    Escape Telegram HTML characters.
    """

    text = str(
        value or ""
    )

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_datetime(
    value,
) -> str:
    """
    Format a datetime safely.
    """

    if value is None:
        return "N/A"

    try:
        return value.strftime(
            "%d %b %Y, %I:%M %p"
        )
    except Exception:
        return str(
            value
        )


# ============================================================================
# Database helpers
# ============================================================================

async def get_user_document(
    client: Client,
    user_id: int,
) -> Optional[dict]:
    """
    Retrieve user document from the database.
    """

    db = getattr(
        client,
        "db",
        None,
    )

    if db is None:
        return None

    try:
        return await db.get_user(
            int(user_id)
        )
    except Exception:
        logger.exception(
            "Unable to get user %s",
            user_id,
        )

        return None


async def ensure_user(
    client: Client,
    message: Message,
) -> Optional[dict]:
    """
    Make sure the user exists in the normal users collection.
    """

    user = message.from_user

    if user is None:
        return None

    user_id = int(
        user.id
    )

    db = getattr(
        client,
        "db",
        None,
    )

    if db is None:
        return None

    try:

        exists = await db.is_user_exist(
            user_id
        )

        if not exists:

            name = (
                user.first_name
                or user.username
                or str(user_id)
            )

            await db.add_user(
                user_id,
                name,
            )

        return await get_user_document(
            client,
            user_id,
        )

    except Exception:
        logger.exception(
            "Unable to ensure user %s",
            user_id,
        )

        return None


# ============================================================================
# /help
# ============================================================================

async def help_command(
    client: Client,
    message: Message,
):
    """
    Display help information.
    """

    await ensure_user(
        client,
        message,
    )

    await message.reply_text(
        HELP_TEXT,
        reply_markup=build_help_keyboard(),
        disable_web_page_preview=True,
    )


# ============================================================================
# /about
# ============================================================================

async def about_command(
    client: Client,
    message: Message,
):
    """
    Display bot information.
    """

    await ensure_user(
        client,
        message,
    )

    text = ABOUT_TEXT.format(
        bot_name=escape_html(
            get_bot_name(
                client
            )
        )
    )

    await message.reply_text(
        text,
        reply_markup=build_about_keyboard(),
        disable_web_page_preview=True,
    )


# ============================================================================
# /id
# ============================================================================

async def id_command(
    client: Client,
    message: Message,
):
    """
    Display Telegram IDs.

    In a private chat:
        user ID

    In a group:
        user ID + chat ID
    """

    user = message.from_user

    if user is None:
        return

    user_id = int(
        user.id
    )

    chat_id = int(
        message.chat.id
    )

    if message.chat.type == "private":

        text = (
            "<b>🆔 Your Telegram ID</b>\n\n"
            f"<code>{user_id}</code>"
        )

    else:

        text = (
            "<b>🆔 Telegram IDs</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"💬 Chat ID: <code>{chat_id}</code>"
        )

    await message.reply_text(
        text
    )


# ============================================================================
# User status
# ============================================================================

async def get_premium_status(
    client: Client,
    user_id: int,
) -> tuple[
    bool,
    Optional[object],
]:
    """
    Determine premium state and expiry.
    """

    db = getattr(
        client,
        "db",
        None,
    )

    if db is None:
        return False, None

    try:

        user = await db.get_user(
            int(user_id)
        )

        if not user:
            return False, None

        expiry = user.get(
            "expiry_time"
        )

        if expiry is None:
            return False, None

        premium = await db.has_premium_access(
            int(user_id)
        )

        return (
            bool(premium),
            expiry,
        )

    except Exception:
        logger.exception(
            "Unable to check premium status"
        )

        return False, None


# ============================================================================
# /me
# ============================================================================

async def me_command(
    client: Client,
    message: Message,
):
    """
    Display user profile.
    """

    user = message.from_user

    if user is None:
        return

    user_id = int(
        user.id
    )

    await ensure_user(
        client,
        message,
    )

    db_user = await get_user_document(
        client,
        user_id,
    )

    premium, expiry = (
        await get_premium_status(
            client,
            user_id,
        )
    )

    first_name = (
        user.first_name
        or "Unknown"
    )

    username = (
        f"@{user.username}"
        if user.username
        else "Not set"
    )

    if premium:

        premium_text = (
            "⭐ <b>Premium</b>"
        )

        expiry_text = (
            format_datetime(
                expiry
            )
        )

    else:

        premium_text = (
            "🆓 <b>Free</b>"
        )

        expiry_text = "N/A"

    created_text = "N/A"

    if db_user:

        created_text = format_datetime(
            db_user.get(
                "created_at"
            )
        )

    text = (
        "<b>👤 My Account</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Name: <b>{escape_html(first_name)}</b>\n"
        f"🔗 Username: {escape_html(username)}\n\n"
        f"💎 Plan: {premium_text}\n"
        f"⏰ Premium expiry: <code>{escape_html(expiry_text)}</code>\n"
        f"📅 Registered: <code>{escape_html(created_text)}</code>\n\n"
        "<i>Your account information is private.</i>"
    )

    await message.reply_text(
        text,
        reply_markup=build_profile_keyboard(),
    )


# ============================================================================
# /status
# ============================================================================

async def status_command(
    client: Client,
    message: Message,
):
    """
    Display account/verification status.
    """

    user = message.from_user

    if user is None:
        return

    user_id = int(
        user.id
    )

    await ensure_user(
        client,
        message,
    )

    premium, expiry = (
        await get_premium_status(
            client,
            user_id,
        )
    )

    # Verification status.
    verification_text = (
        "ℹ️ Not checked"
    )

    try:

        from bot.services.verification import (
            verification,
        )

        group_id = int(
            message.chat.id
        )

        status = await verification.get_status(
            user_id,
            group_id,
        )

        if status.get(
            "allowed"
        ):
            verification_text = (
                "✅ Verified"
            )
        else:

            layer = status.get(
                "required_layer"
            )

            if layer:
                verification_text = (
                    f"🔐 Verification required "
                    f"(Layer {layer})"
                )
            else:
                verification_text = (
                    "⏳ Verification pending"
                )

    except Exception:
        logger.exception(
            "Unable to retrieve verification status"
        )

    if premium:

        plan_text = "⭐ Premium"

        expiry_text = format_datetime(
            expiry
        )

    else:

        plan_text = "🆓 Free"

        expiry_text = "N/A"

    text = (
        "<b>📊 Account Status</b>\n\n"
        f"👤 User: <code>{user_id}</code>\n"
        f"💎 Plan: {plan_text}\n"
        f"⏰ Expiry: <code>{escape_html(expiry_text)}</code>\n"
        f"🔐 Verification: {verification_text}\n"
    )

    await message.reply_text(
        text,
        reply_markup=build_profile_keyboard(),
    )


# ============================================================================
# /cancel
# ============================================================================

async def cancel_command(
    client: Client,
    message: Message,
):
    """
    Cancel the user's current interaction.

    Future conversation states can register their own cancellation
    callbacks through the same service.
    """

    user = message.from_user

    if user is None:
        return

    # Future state manager integration.
    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is not None:

        try:

            clear = getattr(
                state_manager,
                "clear",
                None,
            )

            if clear:
                await clear(
                    int(user.id)
                )

        except Exception:
            logger.exception(
                "Unable to clear user state"
            )

    await message.reply_text(
        "✅ <b>Current operation cancelled.</b>\n\n"
        "You can send a new search whenever you're ready."
    )


# ============================================================================
# Callback: Help
# ============================================================================

async def help_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Open help from inline keyboard.
    """

    await callback_query.answer()

    if not callback_query.message:
        return

    try:

        await callback_query.message.edit_text(
            HELP_TEXT,
            reply_markup=build_help_keyboard(),
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception(
            "Unable to display help callback"
        )


# ============================================================================
# Callback: About
# ============================================================================

async def about_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Open about screen.
    """

    await callback_query.answer()

    if not callback_query.message:
        return

    text = ABOUT_TEXT.format(
        bot_name=escape_html(
            get_bot_name(
                client
            )
        )
    )

    try:

        await callback_query.message.edit_text(
            text,
            reply_markup=build_about_keyboard(),
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception(
            "Unable to display about callback"
        )


# ============================================================================
# Callback: Profile
# ============================================================================

async def profile_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Open user profile from keyboard.
    """

    await callback_query.answer()

    message = (
        callback_query.message
    )

    user = (
        callback_query.from_user
    )

    if message is None or user is None:
        return

    user_id = int(
        user.id
    )

    db_user = await get_user_document(
        client,
        user_id,
    )

    premium, expiry = (
        await get_premium_status(
            client,
            user_id,
        )
    )

    first_name = (
        user.first_name
        or "Unknown"
    )

    username = (
        f"@{user.username}"
        if user.username
        else "Not set"
    )

    if premium:

        premium_text = (
            "⭐ Premium"
        )

        expiry_text = format_datetime(
            expiry
        )

    else:

        premium_text = (
            "🆓 Free"
        )

        expiry_text = "N/A"

    created_text = format_datetime(
        db_user.get(
            "created_at"
        )
        if db_user
        else None
    )

    text = (
        "<b>👤 My Account</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Name: <b>{escape_html(first_name)}</b>\n"
        f"🔗 Username: {escape_html(username)}\n\n"
        f"💎 Plan: <b>{premium_text}</b>\n"
        f"⏰ Expiry: <code>{escape_html(expiry_text)}</code>\n"
        f"📅 Registered: <code>{escape_html(created_text)}</code>"
    )

    try:

        await message.edit_text(
            text,
            reply_markup=build_profile_keyboard(),
        )

    except Exception:
        logger.exception(
            "Unable to display profile"
        )


# ============================================================================
# Callback: Search
# ============================================================================

async def search_menu_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Tell the user how to search.
    """

    await callback_query.answer()

    if not callback_query.message:
        return

    text = (
        "<b>🔎 Search</b>\n\n"
        "Send me the name of the movie, series, "
        "or file you are looking for.\n\n"
        "<b>Examples:</b>\n"
        "<code>Avatar</code>\n"
        "<code>Avengers Endgame 2019</code>\n"
        "<code>Breaking Bad S01</code>\n"
        "<code>RRR 1080p</code>"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📚 Help",
                    callback_data="menu_help",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="user_close",
                ),
            ],
        ]
    )

    try:

        await callback_query.message.edit_text(
            text,
            reply_markup=keyboard,
        )

    except Exception:
        logger.exception(
            "Unable to display search menu"
        )


# ============================================================================
# Callback: Premium
# ============================================================================

async def premium_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Open premium menu.

    The actual purchase/subscription flow will be implemented by the
    premium handler.
    """

    await callback_query.answer()

    if not callback_query.message:
        return

    try:

        from bot.handlers.premium import (
            show_premium_menu,
        )

    except ImportError:

        show_premium_menu = None

    if show_premium_menu:

        try:

            await show_premium_menu(
                client,
                callback_query,
            )

            return

        except Exception:
            logger.exception(
                "Premium menu handler failed"
            )

    await callback_query.message.edit_text(
        "<b>⭐ Premium</b>\n\n"
        "Premium options will be available here.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⬅️ Back",
                        callback_data="user_profile",
                    )
                ]
            ]
        ),
    )


# ============================================================================
# Close callback
# ============================================================================

async def close_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Close a bot menu.
    """

    await callback_query.answer()

    if not callback_query.message:
        return

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
    Register all common user handlers.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    # Commands.
    app.add_handler(
        MessageHandler(
            help_command,
            filters.command(
                "help"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            about_command,
            filters.command(
                "about"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            id_command,
            filters.command(
                "id"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            me_command,
            filters.command(
                "me"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            status_command,
            filters.command(
                "status"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            cancel_command,
            filters.command(
                "cancel"
            ),
        )
    )

    # Menu callbacks.
    app.add_handler(
        CallbackQueryHandler(
            help_callback,
            filters.regex(
                r"^menu_help$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            about_callback,
            filters.regex(
                r"^menu_about$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            profile_callback,
            filters.regex(
                r"^user_profile$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            search_menu_callback,
            filters.regex(
                r"^menu_search$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            premium_callback,
            filters.regex(
                r"^user_premium$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            close_callback,
            filters.regex(
                r"^user_close$"
            ),
        )
    )

    logger.info(
        "Registered user handlers"
    )


# ============================================================================
# Plugin-compatible handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "help"
    )
)
async def help_handler(
    client: Client,
    message: Message,
):
    await help_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "about"
    )
)
async def about_handler(
    client: Client,
    message: Message,
):
    await about_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "id"
    )
)
async def id_handler(
    client: Client,
    message: Message,
):
    await id_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "me"
    )
)
async def me_handler(
    client: Client,
    message: Message,
):
    await me_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "status"
    )
)
async def status_handler(
    client: Client,
    message: Message,
):
    await status_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "cancel"
    )
)
async def cancel_handler(
    client: Client,
    message: Message,
):
    await cancel_command(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^menu_help$"
    )
)
async def help_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await help_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^menu_about$"
    )
)
async def about_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await about_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^user_profile$"
    )
)
async def profile_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await profile_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^menu_search$"
    )
)
async def search_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await search_menu_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^user_premium$"
    )
)
async def premium_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await premium_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^user_close$"
    )
)
async def close_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await close_callback(
        client,
        callback_query,
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "help_command",
    "about_command",
    "id_command",
    "me_command",
    "status_command",
    "cancel_command",
    "help_handler",
    "about_handler",
    "id_handler",
    "me_handler",
    "status_handler",
    "cancel_handler",
    "help_callback",
    "about_callback",
    "profile_callback",
    "search_menu_callback",
    "premium_callback",
    "close_callback",
    "build_help_keyboard",
    "build_profile_keyboard",
    "build_about_keyboard",
    "register",
]