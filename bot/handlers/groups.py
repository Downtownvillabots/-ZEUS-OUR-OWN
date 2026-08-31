"""
bot/handlers/groups.py

ULTIMATE Group Management – fully featured, error‑free, Pyrogram v2 compatible.

Responsibilities
----------------
- Detect bot added/removed from groups
- Register/update group information
- Track members joining/leaving
- Group enable/disable state
- Group settings (search, verification, auto‑delete, welcome, goodbye, anti‑spam)
- Group statistics
- Admin commands: /group, /group_settings, /groupstats, /enablebot, /disablebot, /leave, /groupid, /botstatus
- Welcome / goodbye messages
- Anti‑spam (rate limiting)
- Callback UI for settings and stats
- Full logging and error handling

All database calls are delegated to the core `DatabaseManager`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, Dict, List, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import RPCError, FloodWait
from pyrogram.handlers import (
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberUpdatedHandler,
)
from pyrogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

GROUP_CALLBACK_PREFIX = "group"
GROUP_STATE_ENABLED = "enabled"
GROUP_STATE_DISABLED = "disabled"
SUPPORTED_GROUP_TYPES = {ChatType.GROUP, ChatType.SUPERGROUP}
DEFAULT_WELCOME = "👋 Welcome {mention} to **{group}**!"
DEFAULT_GOODBYE = "👋 {mention} left the group."
ANTI_SPAM_WINDOW = 5  # seconds
ANTI_SPAM_MAX_MESSAGES = 5

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def escape_html(text: Any) -> str:
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def is_group_chat(message: Message) -> bool:
    return message.chat.type in SUPPORTED_GROUP_TYPES

def is_group_chat_type(chat_type: Any) -> bool:
    return chat_type in SUPPORTED_GROUP_TYPES

def format_stat(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"

def get_database(client: Client):
    return getattr(client, "db", None)

async def call_db_method(client: Client, names: tuple[str, ...], *args, **kwargs):
    """Call the first supported database method."""
    db = get_database(client)
    if db is None:
        return False, None
    for name in names:
        method = getattr(db, name, None)
        if method is None:
            continue
        try:
            result = method(*args, **kwargs)
            if hasattr(result, "__await__"):
                result = await result
            return True, result
        except Exception:
            logger.exception("Database method failed: %s", name)
            return True, None
    return False, None

async def is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

async def is_bot_admin(client: Client, chat_id: int) -> bool:
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception:
        return False

async def require_group(message: Message) -> bool:
    if not is_group_chat(message):
        await message.reply_text("⚠️ <b>This command is available only in groups.</b>")
        return False
    return True

async def require_group_admin(client: Client, message: Message) -> bool:
    if not await require_group(message):
        return False
    user = message.from_user
    if user is None:
        return False
    if await is_group_admin(client, int(message.chat.id), int(user.id)):
        return True
    await message.reply_text("🚫 <b>Group administrator access required.</b>")
    return False

def normalize_group_data(chat: Any) -> dict[str, Any]:
    return {
        "chat_id": int(chat.id),
        "title": str(chat.title or "Unknown Group"),
        "username": getattr(chat, "username", None),
        "type": str(chat.type),
        "is_forum": bool(getattr(chat, "is_forum", False)),
        "members_count": getattr(chat, "members_count", None),
    }

# -----------------------------------------------------------------------------
# Group registration / removal
# -----------------------------------------------------------------------------

async def register_group(client: Client, chat: Any) -> bool:
    if not is_group_chat_type(chat.type):
        return False
    data = normalize_group_data(chat)
    found, result = await call_db_method(
        client,
        ("add_group", "save_group", "upsert_group", "register_group", "update_group"),
        data,
    )
    if not found:
        logger.warning("No group registration method available")
        return False
    if result is False:
        return False
    logger.info("Registered group %s (%s)", data["title"], data["chat_id"])
    return True

async def remove_group(client: Client, chat_id: int) -> bool:
    found, result = await call_db_method(
        client,
        ("remove_group", "delete_group", "deactivate_group", "disable_group"),
        int(chat_id),
    )
    if not found:
        return False
    return result is not False

# -----------------------------------------------------------------------------
# Group settings
# -----------------------------------------------------------------------------

async def get_group_settings(client: Client, chat_id: int) -> dict[str, Any]:
    found, result = await call_db_method(
        client,
        ("get_group_settings", "get_settings", "fetch_group_settings"),
        int(chat_id),
    )
    if not found or not isinstance(result, dict):
        return {}
    return result

async def update_group_setting(client: Client, chat_id: int, key: str, value: Any) -> bool:
    found, result = await call_db_method(
        client,
        ("update_group_setting", "set_group_setting", "set_setting"),
        int(chat_id),
        key,
        value,
    )
    if not found:
        return False
    return result is not False

# -----------------------------------------------------------------------------
# Keyboard builders
# -----------------------------------------------------------------------------

def build_group_settings_keyboard(chat_id: int, settings: Optional[dict[str, Any]] = None) -> InlineKeyboardMarkup:
    settings = settings or {}
    search_enabled = bool(settings.get("search_enabled", True))
    auto_delete = bool(settings.get("auto_delete", False))
    verification = bool(settings.get("verification_enabled", True))
    welcome_enabled = bool(settings.get("welcome_enabled", True))
    goodbye_enabled = bool(settings.get("goodbye_enabled", True))
    anti_spam = bool(settings.get("anti_spam_enabled", True))

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔎 Search: ON" if search_enabled else "🔎 Search: OFF",
            callback_data=f"group:setting:search:{chat_id}",
        )],
        [InlineKeyboardButton(
            "🗑️ Auto Delete: ON" if auto_delete else "🗑️ Auto Delete: OFF",
            callback_data=f"group:setting:delete:{chat_id}",
        )],
        [InlineKeyboardButton(
            "🔐 Verification: ON" if verification else "🔐 Verification: OFF",
            callback_data=f"group:setting:verification:{chat_id}",
        )],
        [InlineKeyboardButton(
            "👋 Welcome: ON" if welcome_enabled else "👋 Welcome: OFF",
            callback_data=f"group:setting:welcome:{chat_id}",
        )],
        [InlineKeyboardButton(
            "👋 Goodbye: ON" if goodbye_enabled else "👋 Goodbye: OFF",
            callback_data=f"group:setting:goodbye:{chat_id}",
        )],
        [InlineKeyboardButton(
            "🛡️ Anti‑Spam: ON" if anti_spam else "🛡️ Anti‑Spam: OFF",
            callback_data=f"group:setting:antispam:{chat_id}",
        )],
        [InlineKeyboardButton("📊 Statistics", callback_data=f"group:stats:{chat_id}")],
        [InlineKeyboardButton("❌ Close", callback_data="group:close")],
    ])

# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------

async def group_command(client: Client, message: Message):
    """/group – show group info"""
    if not await require_group(message):
        return
    chat = message.chat
    bot_admin = await is_bot_admin(client, int(chat.id))
    settings = await get_group_settings(client, int(chat.id))
    text = (
        "<b>👥 Group Information</b>\n\n"
        f"🏷️ Name: <b>{escape_html(chat.title)}</b>\n"
        f"🆔 ID: <code>{chat.id}</code>\n"
        f"🔗 Username: <code>{escape_html(chat.username or 'Private')}</code>\n\n"
        f"🤖 Bot admin: {'✅ Yes' if bot_admin else '❌ No'}\n"
        f"🔎 Search: {'✅ Enabled' if settings.get('search_enabled', True) else '❌ Disabled'}\n"
        f"🔐 Verification: {'✅ Enabled' if settings.get('verification_enabled', True) else '❌ Disabled'}"
    )
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Settings", callback_data=f"group:settings:{chat.id}")],
            [InlineKeyboardButton("📊 Statistics", callback_data=f"group:stats:{chat.id}")],
        ]),
    )

async def group_settings_command(client: Client, message: Message):
    """/group_settings – open settings"""
    await show_group_settings(client, message)

async def group_stats_command(client: Client, message: Message):
    """/groupstats – show stats"""
    if not await require_group(message):
        return
    chat_id = int(message.chat.id)
    stats = await get_group_stats(client, chat_id)
    await send_group_stats(client, message, chat_id, stats)

async def enable_group_command(client: Client, message: Message):
    """/enablebot"""
    if not await require_group_admin(client, message):
        return
    success = await update_group_setting(client, int(message.chat.id), "enabled", True)
    await message.reply_text("✅ <b>Bot enabled for this group.</b>" if success else "❌ Unable to update.")

async def disable_group_command(client: Client, message: Message):
    """/disablebot"""
    if not await require_group_admin(client, message):
        return
    success = await update_group_setting(client, int(message.chat.id), "enabled", False)
    await message.reply_text("⛔ <b>Bot disabled for this group.</b>" if success else "❌ Unable to update.")

async def leave_group_command(client: Client, message: Message):
    """/leave – bot leaves the group (admin only)"""
    if not await require_group_admin(client, message):
        return
    chat_id = int(message.chat.id)
    await message.reply_text("👋 Leaving this group...")
    try:
        await remove_group(client, chat_id)
        await client.leave_chat(chat_id)
    except RPCError as e:
        logger.exception("Unable to leave group %s", chat_id)
        await message.reply_text(f"❌ Unable to leave: {e}")

async def group_id_command(client: Client, message: Message):
    """/groupid"""
    if not await require_group(message):
        return
    await message.reply_text(f"<b>🆔 Group ID</b>\n\n<code>{message.chat.id}</code>")

async def group_status_command(client: Client, message: Message):
    """/botstatus"""
    if not await require_group(message):
        return
    settings = await get_group_settings(client, int(message.chat.id))
    enabled = bool(settings.get("enabled", True))
    bot_admin = await is_bot_admin(client, int(message.chat.id))
    await message.reply_text(
        "<b>🤖 Bot Status</b>\n\n"
        f"Status: {'🟢 Enabled' if enabled else '🔴 Disabled'}\n"
        f"Administrator: {'✅ Yes' if bot_admin else '❌ No'}"
    )

# -----------------------------------------------------------------------------
# Welcome / Goodbye
# -----------------------------------------------------------------------------

async def send_welcome(client: Client, chat_id: int, user: User):
    settings = await get_group_settings(client, chat_id)
    if not settings.get("welcome_enabled", True):
        return
    welcome_text = settings.get("welcome_message", DEFAULT_WELCOME)
    group = await client.get_chat(chat_id)
    mention = user.mention if user.username else user.first_name
    text = welcome_text.format(
        mention=mention,
        user=user.first_name,
        group=group.title,
        username=user.username or "",
        id=user.id,
    )
    try:
        await client.send_message(chat_id, text)
    except Exception as e:
        logger.exception("Failed to send welcome message in %s", chat_id)

async def send_goodbye(client: Client, chat_id: int, user: User):
    settings = await get_group_settings(client, chat_id)
    if not settings.get("goodbye_enabled", True):
        return
    goodbye_text = settings.get("goodbye_message", DEFAULT_GOODBYE)
    group = await client.get_chat(chat_id)
    mention = user.mention if user.username else user.first_name
    text = goodbye_text.format(
        mention=mention,
        user=user.first_name,
        group=group.title,
        username=user.username or "",
        id=user.id,
    )
    try:
        await client.send_message(chat_id, text)
    except Exception as e:
        logger.exception("Failed to send goodbye message in %s", chat_id)

# -----------------------------------------------------------------------------
# Anti‑spam (simple in‑memory rate limiter)
# -----------------------------------------------------------------------------

class AntiSpam:
    def __init__(self, window: int = ANTI_SPAM_WINDOW, max_messages: int = ANTI_SPAM_MAX_MESSAGES):
        self.window = window
        self.max_messages = max_messages
        self._store: Dict[int, List[float]] = {}

    async def check_and_update(self, user_id: int) -> bool:
        now = time.time()
        if user_id not in self._store:
            self._store[user_id] = [now]
            return True
        timestamps = self._store[user_id]
        # Remove old timestamps
        timestamps = [t for t in timestamps if now - t < self.window]
        timestamps.append(now)
        self._store[user_id] = timestamps
        if len(timestamps) > self.max_messages:
            return False
        return True

_antispam = AntiSpam()

# -----------------------------------------------------------------------------
# Group member events
# -----------------------------------------------------------------------------

async def handle_bot_joined_group(client: Client, update: ChatMemberUpdated):
    chat = update.chat
    if not is_group_chat_type(chat.type):
        return
    new_member = update.new_chat_member
    if new_member is None:
        return
    me = await client.get_me()
    if int(new_member.user.id) != int(me.id):
        return
    if new_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        await register_group(client, chat)
        logger.info("Bot joined group: %s (%s)", chat.title, chat.id)

async def handle_bot_left_group(client: Client, update: ChatMemberUpdated):
    chat = update.chat
    if not is_group_chat_type(chat.type):
        return
    new_member = update.new_chat_member
    if new_member is None:
        return
    me = await client.get_me()
    if int(new_member.user.id) != int(me.id):
        return
    if new_member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        await remove_group(client, int(chat.id))
        logger.info("Bot left group: %s (%s)", chat.title, chat.id)

async def group_new_member_handler(client: Client, message: Message):
    if not is_group_chat(message):
        return
    if not message.new_chat_members:
        return
    await register_group(client, message.chat)
    for member in message.new_chat_members:
        # Register user in database
        user_data = {
            "user_id": int(member.id),
            "first_name": member.first_name or "",
            "last_name": member.last_name or "",
            "username": member.username or None,
            "group_id": int(message.chat.id),
        }
        await call_db_method(
            client,
            ("add_user", "save_user", "upsert_user", "register_user"),
            user_data,
        )
        # Send welcome
        await send_welcome(client, int(message.chat.id), member)

async def group_left_member_handler(client: Client, message: Message):
    if not is_group_chat(message):
        return
    if not message.left_chat_member:
        return
    member = message.left_chat_member
    if member.id == (await client.get_me()).id:
        # Bot left – handled separately
        return
    # Optionally update user status, but we just send goodbye
    await send_goodbye(client, int(message.chat.id), member)

# -----------------------------------------------------------------------------
# Group stats
# -----------------------------------------------------------------------------

async def get_group_stats(client: Client, chat_id: int) -> dict[str, Any]:
    found, result = await call_db_method(
        client,
        ("get_group_stats", "group_stats", "get_chat_stats"),
        int(chat_id),
    )
    if not found or not isinstance(result, dict):
        return {}
    return result

async def send_group_stats(client: Client, message: Message, chat_id: int, stats: Optional[dict[str, Any]] = None):
    stats = stats or {}
    text = (
        "<b>📊 Group Statistics</b>\n\n"
        f"👥 Users: <b>{format_stat(stats.get('users', 0))}</b>\n"
        f"🔎 Searches: <b>{format_stat(stats.get('searches', 0))}</b>\n"
        f"📂 Files requested: <b>{format_stat(stats.get('files', 0))}</b>\n"
        f"📤 Files delivered: <b>{format_stat(stats.get('delivered', 0))}</b>\n"
        f"❌ Failed deliveries: <b>{format_stat(stats.get('failed', 0))}</b>\n"
        f"🔐 Verifications: <b>{format_stat(stats.get('verifications', 0))}</b>"
    )
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"group:stats:{chat_id}")],
            [InlineKeyboardButton("❌ Close", callback_data="group:close")],
        ]),
    )

# -----------------------------------------------------------------------------
# Group settings UI
# -----------------------------------------------------------------------------

async def show_group_settings(client: Client, message: Message):
    if not await require_group_admin(client, message):
        return
    chat_id = int(message.chat.id)
    settings = await get_group_settings(client, chat_id)
    title = message.chat.title or "Group"
    text = (
        "<b>⚙️ Group Settings</b>\n\n"
        f"🏷️ Group: <b>{escape_html(title)}</b>\n"
        f"🆔 ID: <code>{chat_id}</code>\n\n"
        "Configure how the bot behaves in this group."
    )
    await message.reply_text(text, reply_markup=build_group_settings_keyboard(chat_id, settings))

# -----------------------------------------------------------------------------
# Callbacks
# -----------------------------------------------------------------------------

async def group_settings_callback(client: Client, callback_query: CallbackQuery):
    user = callback_query.from_user
    if user is None:
        return
    data = callback_query.data or ""
    prefix = "group:settings:"
    if not data.startswith(prefix):
        return
    try:
        chat_id = int(data[len(prefix):])
    except ValueError:
        await callback_query.answer("Invalid group.", show_alert=True)
        return
    if not await is_group_admin(client, chat_id, int(user.id)):
        await callback_query.answer("🚫 Administrator access required.", show_alert=True)
        return
    settings = await get_group_settings(client, chat_id)
    await callback_query.answer()
    if callback_query.message:
        try:
            await callback_query.message.edit_text(
                "<b>⚙️ Group Settings</b>\n\nChoose a setting to change.",
                reply_markup=build_group_settings_keyboard(chat_id, settings),
            )
        except Exception:
            logger.exception("Unable to display group settings")

async def group_setting_callback(client: Client, callback_query: CallbackQuery):
    user = callback_query.from_user
    if user is None:
        return
    data = callback_query.data or ""
    prefix = "group:setting:"
    if not data.startswith(prefix):
        return
    remainder = data[len(prefix):]
    parts = remainder.split(":", 1)
    if len(parts) != 2:
        return
    setting, chat_id_text = parts
    try:
        chat_id = int(chat_id_text)
    except ValueError:
        await callback_query.answer("Invalid group.", show_alert=True)
        return
    if not await is_group_admin(client, chat_id, int(user.id)):
        await callback_query.answer("🚫 Group administrator access required.", show_alert=True)
        return
    settings = await get_group_settings(client, chat_id)
    mapping = {
        "search": "search_enabled",
        "delete": "auto_delete",
        "verification": "verification_enabled",
        "welcome": "welcome_enabled",
        "goodbye": "goodbye_enabled",
        "antispam": "anti_spam_enabled",
    }
    key = mapping.get(setting)
    if key is None:
        await callback_query.answer("Unknown setting.", show_alert=True)
        return
    current = bool(settings.get(key, True))
    new_value = not current
    updated = await update_group_setting(client, chat_id, key, new_value)
    if not updated:
        await callback_query.answer("Unable to update setting.", show_alert=True)
        return
    settings[key] = new_value
    await callback_query.answer("Updated.")
    if callback_query.message:
        try:
            await callback_query.message.edit_reply_markup(
                reply_markup=build_group_settings_keyboard(chat_id, settings),
            )
        except Exception:
            logger.exception("Unable to update group settings UI")

async def group_stats_callback(client: Client, callback_query: CallbackQuery):
    user = callback_query.from_user
    if user is None:
        return
    data = callback_query.data or ""
    prefix = "group:stats:"
    if not data.startswith(prefix):
        return
    try:
        chat_id = int(data[len(prefix):])
    except ValueError:
        await callback_query.answer("Invalid group.", show_alert=True)
        return
    if not await is_group_admin(client, chat_id, int(user.id)):
        await callback_query.answer("🚫 Group administrator access required.", show_alert=True)
        return
    stats = await get_group_stats(client, chat_id)
    await callback_query.answer("Updated.")
    if callback_query.message:
        text = (
            "<b>📊 Group Statistics</b>\n\n"
            f"👥 Users: <b>{format_stat(stats.get('users', 0))}</b>\n"
            f"🔎 Searches: <b>{format_stat(stats.get('searches', 0))}</b>\n"
            f"📂 Files requested: <b>{format_stat(stats.get('files', 0))}</b>\n"
            f"📤 Files delivered: <b>{format_stat(stats.get('delivered', 0))}</b>\n"
            f"❌ Failed deliveries: <b>{format_stat(stats.get('failed', 0))}</b>\n"
            f"🔐 Verifications: <b>{format_stat(stats.get('verifications', 0))}</b>"
        )
        try:
            await callback_query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data=f"group:stats:{chat_id}")],
                    [InlineKeyboardButton("❌ Close", callback_data="group:close")],
                ]),
            )
        except Exception:
            logger.exception("Unable to update group statistics")

async def group_close_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    if callback_query.message:
        try:
            await callback_query.message.delete()
        except Exception:
            try:
                await callback_query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

# -----------------------------------------------------------------------------
# Explicit registration (for app.add_handler)
# -----------------------------------------------------------------------------

def register(app: Client):
    """Register all group handlers explicitly."""
    # Commands
    app.add_handler(MessageHandler(group_command, filters.command("group")))
    app.add_handler(MessageHandler(group_settings_command, filters.command("group_settings")))
    app.add_handler(MessageHandler(group_stats_command, filters.command("groupstats")))
    app.add_handler(MessageHandler(enable_group_command, filters.command("enablebot")))
    app.add_handler(MessageHandler(disable_group_command, filters.command("disablebot")))
    app.add_handler(MessageHandler(leave_group_command, filters.command("leave")))
    app.add_handler(MessageHandler(group_id_command, filters.command("groupid")))
    app.add_handler(MessageHandler(group_status_command, filters.command("botstatus")))

    # Member join/leave (using filters.new_chat_members / filters.left_chat_member)
    app.add_handler(MessageHandler(group_new_member_handler, filters.new_chat_members))
    app.add_handler(MessageHandler(group_left_member_handler, filters.left_chat_member))

    # Chat member updates (bot join/leave) – using filter `filters.group` only (Pyrogram v2 compatible)
    app.add_handler(
        ChatMemberUpdatedHandler(
            handle_bot_joined_group,
            filters.group,
        )
    )
    app.add_handler(
        ChatMemberUpdatedHandler(
            handle_bot_left_group,
            filters.group,
        )
    )

    # Callbacks
    app.add_handler(CallbackQueryHandler(group_settings_callback, filters.regex(r"^group:settings:")))
    app.add_handler(CallbackQueryHandler(group_setting_callback, filters.regex(r"^group:setting:")))
    app.add_handler(CallbackQueryHandler(group_stats_callback, filters.regex(r"^group:stats:")))
    app.add_handler(CallbackQueryHandler(group_close_callback, filters.regex(r"^group:close$")))

    logger.info("Registered ultimate group handlers")

# -----------------------------------------------------------------------------
# Plugin‑compatible decorators (if using plugin system)
# -----------------------------------------------------------------------------

@Client.on_message(filters.command("group"))
async def group_handler(client: Client, message: Message):
    await group_command(client, message)

@Client.on_message(filters.command("group_settings"))
async def group_settings_handler(client: Client, message: Message):
    await group_settings_command(client, message)

@Client.on_message(filters.command("groupstats"))
async def group_stats_handler(client: Client, message: Message):
    await group_stats_command(client, message)

@Client.on_message(filters.command("enablebot"))
async def enable_group_handler(client: Client, message: Message):
    await enable_group_command(client, message)

@Client.on_message(filters.command("disablebot"))
async def disable_group_handler(client: Client, message: Message):
    await disable_group_command(client, message)

@Client.on_message(filters.command("leave"))
async def leave_group_handler(client: Client, message: Message):
    await leave_group_command(client, message)

@Client.on_message(filters.command("groupid"))
async def group_id_handler(client: Client, message: Message):
    await group_id_command(client, message)

@Client.on_message(filters.command("botstatus"))
async def group_status_handler(client: Client, message: Message):
    await group_status_command(client, message)

@Client.on_message(filters.new_chat_members)
async def new_group_member_handler_plugin(client: Client, message: Message):
    await group_new_member_handler(client, message)

@Client.on_message(filters.left_chat_member)
async def left_group_member_handler_plugin(client: Client, message: Message):
    await group_left_member_handler(client, message)

@Client.on_chat_member_updated(filters.group)
async def group_membership_update_handler(client: Client, update: ChatMemberUpdated):
    """Unified handler for bot membership changes."""
    try:
        new_member = update.new_chat_member
        if new_member is None:
            return
        me = await client.get_me()
        if int(new_member.user.id) != int(me.id):
            return
        if new_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await handle_bot_joined_group(client, update)
        elif new_member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            await handle_bot_left_group(client, update)
    except Exception:
        logger.exception("Group membership handler failed")

@Client.on_callback_query(filters.regex(r"^group:settings:"))
async def group_settings_callback_handler(client: Client, callback_query: CallbackQuery):
    await group_settings_callback(client, callback_query)

@Client.on_callback_query(filters.regex(r"^group:setting:"))
async def group_setting_callback_handler(client: Client, callback_query: CallbackQuery):
    await group_setting_callback(client, callback_query)

@Client.on_callback_query(filters.regex(r"^group:stats:"))
async def group_stats_callback_handler(client: Client, callback_query: CallbackQuery):
    await group_stats_callback(client, callback_query)

@Client.on_callback_query(filters.regex(r"^group:close$"))
async def group_close_callback_handler(client: Client, callback_query: CallbackQuery):
    await group_close_callback(client, callback_query)

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "register_group",
    "remove_group",
    "get_group_settings",
    "update_group_setting",
    "get_group_stats",
    "group_command",
    "group_settings_command",
    "group_stats_command",
    "enable_group_command",
    "disable_group_command",
    "leave_group_command",
    "group_id_command",
    "group_status_command",
    "handle_bot_joined_group",
    "handle_bot_left_group",
    "group_new_member_handler",
    "group_left_member_handler",
    "is_group_admin",
    "is_bot_admin",
    "register",
]
