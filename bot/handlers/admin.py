"""
Admin handlers for the new bot.

Responsibilities:
- Admin-only commands
- User/group management
- Premium management
- Maintenance control
- Bot-level settings
- Broadcast entry points
- Statistics
- Admin help
- Safe callback handling

This module intentionally keeps business logic out of handlers.
Database operations belong to database/services modules.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from info import ADMINS

# ---------------------------------------------------------------------------
# Service imports
# ---------------------------------------------------------------------------

# These imports are intentionally tolerant so the handler can be introduced
# while the rest of the project is still being assembled.
try:
    from bot.database.core import db
except ImportError:
    db = None

try:
    from bot.database.users import user_db
except ImportError:
    user_db = None

try:
    from bot.database.groups import group_db
except ImportError:
    group_db = None

try:
    from bot.database.premium import premium_db
except ImportError:
    premium_db = None

try:
    from bot.services.broadcast import (
        users_broadcast,
        groups_broadcast,
    )
except ImportError:
    users_broadcast = None
    groups_broadcast = None

try:
    from bot.services.settings import (
        get_settings,
        save_group_settings,
    )
except ImportError:
    get_settings = None
    save_group_settings = None


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ============================================================================
# ADMIN STATE
# ============================================================================

# Temporary state for interactive admin operations.
#
# Example:
# admin_states[user_id] = {
#     "action": "broadcast",
#     "created_at": datetime(...)
# }
#
# This is intentionally in-memory. Persistent state should be implemented
# later only if required.
admin_states = {}

# Prevent multiple destructive/admin operations simultaneously.
admin_operation_lock = asyncio.Lock()


# ============================================================================
# HELPERS
# ============================================================================

def is_admin(user_id: Optional[int]) -> bool:
    """Return True when a Telegram user is an administrator."""
    if user_id is None:
        return False

    try:
        return int(user_id) in [int(x) for x in ADMINS]
    except Exception:
        return False


def admin_only():
    """Reusable Pyrogram admin filter."""
    return filters.user(ADMINS)


def set_admin_state(user_id: int, action: str, **data):
    """Create/update temporary admin state."""
    admin_states[int(user_id)] = {
        "action": action,
        "created_at": datetime.utcnow(),
        **data,
    }


def get_admin_state(user_id: int):
    """Return temporary admin state."""
    return admin_states.get(int(user_id))


def clear_admin_state(user_id: int):
    """Remove temporary admin state."""
    admin_states.pop(int(user_id), None)


def admin_keyboard():
    """Main admin control panel."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 Users",
                    callback_data="admin#users",
                ),
                InlineKeyboardButton(
                    "💬 Groups",
                    callback_data="admin#groups",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💎 Premium",
                    callback_data="admin#premium",
                ),
                InlineKeyboardButton(
                    "📊 Statistics",
                    callback_data="admin#stats",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 Broadcast",
                    callback_data="admin#broadcast",
                ),
                InlineKeyboardButton(
                    "⚙️ Bot Settings",
                    callback_data="admin#settings",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔧 Maintenance",
                    callback_data="admin#maintenance",
                ),
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="admin#close",
                ),
            ],
        ]
    )


def back_keyboard():
    """Back button used throughout admin menus."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="admin#home",
                ),
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data="admin#close",
                ),
            ]
        ]
    )


def format_number(value) -> str:
    """Format integer-like values safely."""
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def format_datetime(value) -> str:
    """Format a datetime for Telegram output."""
    if not value:
        return "N/A"

    try:
        return value.strftime("%d %b %Y, %H:%M:%S")
    except Exception:
        return str(value)


async def safe_answer(
    query: CallbackQuery,
    text: str = "",
    show_alert: bool = False,
):
    """Answer callback without allowing expired-query errors to crash."""
    try:
        await query.answer(text, show_alert=show_alert)
    except Exception:
        pass


async def safe_edit(
    query: CallbackQuery,
    text: str,
    reply_markup=None,
):
    """Safely edit callback message."""
    try:
        await query.message.edit_text(
            text,
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to edit admin message")


# ============================================================================
# ADMIN START / PANEL
# ============================================================================

@Client.on_message(
    filters.command("admin") & filters.private & filters.incoming & admin_only()
)
async def admin_panel(client: Client, message: Message):
    """Open the main administrator panel."""

    await message.reply_text(
        (
            "<b>🛠 Administrator Panel</b>\n\n"
            "Welcome to the bot control center.\n\n"
            "Choose an operation below."
        ),
        reply_markup=admin_keyboard(),
    )


@Client.on_message(
    filters.command("panel") & filters.private & filters.incoming & admin_only()
)
async def admin_panel_alias(client: Client, message: Message):
    """Alias for /admin."""

    await admin_panel(client, message)


@Client.on_message(
    filters.command("adminhelp")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def admin_help(client: Client, message: Message):
    """Display administrator command reference."""

    text = """
<b>🛠 Admin Commands</b>

<b>Management</b>
/admin - Open admin panel
/stats - Bot statistics
/users - User statistics
/groups - Group statistics

<b>Premium</b>
/addpremium USER_ID DAYS
/delpremium USER_ID
/premium

<b>Moderation</b>
/ban USER_ID [reason]
/unban USER_ID

<b>Maintenance</b>
/maintenance
/maintenance on
/maintenance off

<b>Broadcast</b>
/broadcast
"""

    await message.reply_text(
        text,
        reply_markup=back_keyboard(),
    )


# ============================================================================
# STATISTICS
# ============================================================================

async def collect_statistics():
    """
    Collect available bot statistics.

    The function supports the modular database architecture and gracefully
    falls back to zero when a service is not available yet.
    """

    users = 0
    groups = 0
    premium = 0

    try:
        if user_db and hasattr(user_db, "total_users_count"):
            users = await user_db.total_users_count()
        elif db and hasattr(db, "total_users_count"):
            users = await db.total_users_count()
    except Exception:
        logger.exception("Failed to retrieve user count")

    try:
        if group_db and hasattr(group_db, "total_chat_count"):
            groups = await group_db.total_chat_count()
        elif db and hasattr(db, "total_chat_count"):
            groups = await db.total_chat_count()
    except Exception:
        logger.exception("Failed to retrieve group count")

    try:
        if premium_db and hasattr(premium_db, "all_premium_users"):
            premium = await premium_db.all_premium_users()
        elif db and hasattr(db, "all_premium_users"):
            premium = await db.all_premium_users()
    except Exception:
        logger.exception("Failed to retrieve premium count")

    return {
        "users": users,
        "groups": groups,
        "premium": premium,
    }


@Client.on_message(
    filters.command("stats") & filters.private & filters.incoming & admin_only()
)
async def statistics_command(client: Client, message: Message):
    """Show bot statistics."""

    stats = await collect_statistics()

    text = (
        "<b>📊 Bot Statistics</b>\n\n"
        f"👤 Users: <code>{format_number(stats['users'])}</code>\n"
        f"👥 Groups: <code>{format_number(stats['groups'])}</code>\n"
        f"💎 Premium: <code>{format_number(stats['premium'])}</code>\n\n"
        f"🕐 Generated: <code>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</code>"
    )

    await message.reply_text(
        text,
        reply_markup=back_keyboard(),
    )


@Client.on_message(
    filters.command("users") & filters.private & filters.incoming & admin_only()
)
async def users_statistics(client: Client, message: Message):
    """Show user count."""

    stats = await collect_statistics()

    await message.reply_text(
        (
            "<b>👥 User Statistics</b>\n\n"
            f"Total users: <code>{format_number(stats['users'])}</code>"
        ),
        reply_markup=back_keyboard(),
    )


@Client.on_message(
    filters.command("groups") & filters.private & filters.incoming & admin_only()
)
async def groups_statistics(client: Client, message: Message):
    """Show group count."""

    stats = await collect_statistics()

    await message.reply_text(
        (
            "<b>💬 Group Statistics</b>\n\n"
            f"Total groups: <code>{format_number(stats['groups'])}</code>"
        ),
        reply_markup=back_keyboard(),
    )


# ============================================================================
# USER MANAGEMENT
# ============================================================================

@Client.on_message(
    filters.command("ban") & filters.private & filters.incoming & admin_only()
)
async def ban_user_command(client: Client, message: Message):
    """Ban a user."""

    if len(message.command) < 2:
        return await message.reply_text(
            "Usage:\n<code>/ban USER_ID [reason]</code>"
        )

    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")

    reason = " ".join(message.command[2:]).strip() or "No Reason"

    try:
        if user_db and hasattr(user_db, "ban_user"):
            await user_db.ban_user(user_id, reason)
        elif db and hasattr(db, "ban_user"):
            await db.ban_user(user_id, reason)
        else:
            return await message.reply_text(
                "❌ User database service is not available."
            )

        await message.reply_text(
            (
                "<b>🚫 User Banned</b>\n\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Reason: <code>{reason}</code>"
            )
        )

    except Exception as e:
        logger.exception("Failed to ban user")
        await message.reply_text(
            f"❌ Failed to ban user.\n<code>{e}</code>"
        )


@Client.on_message(
    filters.command("unban") & filters.private & filters.incoming & admin_only()
)
async def unban_user_command(client: Client, message: Message):
    """Remove a user ban."""

    if len(message.command) < 2:
        return await message.reply_text(
            "Usage:\n<code>/unban USER_ID</code>"
        )

    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")

    try:
        if user_db and hasattr(user_db, "remove_ban"):
            await user_db.remove_ban(user_id)
        elif db and hasattr(db, "remove_ban"):
            await db.remove_ban(user_id)
        else:
            return await message.reply_text(
                "❌ User database service is not available."
            )

        await message.reply_text(
            f"✅ User <code>{user_id}</code> has been unbanned."
        )

    except Exception as e:
        logger.exception("Failed to unban user")
        await message.reply_text(
            f"❌ Failed to unban user.\n<code>{e}</code>"
        )


# ============================================================================
# PREMIUM MANAGEMENT
# ============================================================================

@Client.on_message(
    filters.command("addpremium")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def add_premium_command(client: Client, message: Message):
    """
    Add premium access.

    Usage:
        /addpremium USER_ID DAYS
    """

    if len(message.command) < 3:
        return await message.reply_text(
            "Usage:\n<code>/addpremium USER_ID DAYS</code>"
        )

    try:
        user_id = int(message.command[1])
        days = int(message.command[2])

        if days <= 0:
            raise ValueError

    except ValueError:
        return await message.reply_text(
            "❌ User ID and days must be valid positive integers."
        )

    expiry = datetime.utcnow() + timedelta(days=days)

    try:
        if premium_db and hasattr(premium_db, "update_user"):
            await premium_db.update_user(
                {
                    "id": user_id,
                    "expiry_time": expiry,
                }
            )
        elif db and hasattr(db, "update_user"):
            await db.update_user(
                {
                    "id": user_id,
                    "expiry_time": expiry,
                }
            )
        else:
            return await message.reply_text(
                "❌ Premium database service is not available."
            )

        await message.reply_text(
            (
                "<b>💎 Premium Activated</b>\n\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Duration: <code>{days} days</code>\n"
                f"Expires: <code>{format_datetime(expiry)} UTC</code>"
            )
        )

    except Exception as e:
        logger.exception("Failed to add premium")
        await message.reply_text(
            f"❌ Failed to add premium.\n<code>{e}</code>"
        )


@Client.on_message(
    filters.command("delpremium")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def remove_premium_command(client: Client, message: Message):
    """Remove premium access."""

    if len(message.command) < 2:
        return await message.reply_text(
            "Usage:\n<code>/delpremium USER_ID</code>"
        )

    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")

    try:
        if premium_db and hasattr(premium_db, "remove_premium_access"):
            await premium_db.remove_premium_access(user_id)
        elif db and hasattr(db, "remove_premium_access"):
            await db.remove_premium_access(user_id)
        else:
            return await message.reply_text(
                "❌ Premium database service is not available."
            )

        await message.reply_text(
            f"✅ Premium access removed from <code>{user_id}</code>."
        )

    except Exception as e:
        logger.exception("Failed to remove premium")
        await message.reply_text(
            f"❌ Failed to remove premium.\n<code>{e}</code>"
        )


@Client.on_message(
    filters.command("premium")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def premium_statistics(client: Client, message: Message):
    """Show premium statistics."""

    stats = await collect_statistics()

    await message.reply_text(
        (
            "<b>💎 Premium Statistics</b>\n\n"
            f"Active premium users: "
            f"<code>{format_number(stats['premium'])}</code>"
        ),
        reply_markup=back_keyboard(),
    )


# ============================================================================
# MAINTENANCE
# ============================================================================

@Client.on_message(
    filters.command("maintenance")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def maintenance_command(client: Client, message: Message):
    """
    Toggle or inspect maintenance mode.

    Supported:
        /maintenance
        /maintenance on
        /maintenance off
    """

    argument = None

    if len(message.command) > 1:
        argument = message.command[1].lower().strip()

    # If no argument, show control menu.
    if argument not in {"on", "off"}:
        return await message.reply_text(
            (
                "<b>🔧 Maintenance Mode</b>\n\n"
                "Choose an action."
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Enable",
                            callback_data="maintenance#on",
                        ),
                        InlineKeyboardButton(
                            "🔴 Disable",
                            callback_data="maintenance#off",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Back",
                            callback_data="admin#home",
                        )
                    ],
                ]
            ),
        )

    await set_maintenance(client, message.from_user.id, argument == "on")

    await message.reply_text(
        (
            "🔧 Maintenance mode "
            f"<b>{'enabled' if argument == 'on' else 'disabled'}</b>."
        )
    )


async def set_maintenance(client, bot_id: int, enabled: bool):
    """Persist maintenance status."""

    try:
        if db and hasattr(db, "update_maintenance_status"):
            await db.update_maintenance_status(bot_id, enabled)
            return True
    except Exception:
        logger.exception("Failed to update maintenance status")

    return False


# ============================================================================
# BROADCAST
# ============================================================================

@Client.on_message(
    filters.command("broadcast")
    & filters.private
    & filters.incoming
    & admin_only()
)
async def broadcast_command(client: Client, message: Message):
    """
    Start broadcast workflow.

    The admin must reply to the message that should be broadcast.
    """

    if not message.reply_to_message:
        return await message.reply_text(
            (
                "<b>📢 Broadcast</b>\n\n"
                "Reply to the message you want to broadcast and use:\n"
                "<code>/broadcast</code>"
            )
        )

    set_admin_state(
        message.from_user.id,
        "broadcast",
        message_id=message.reply_to_message.id,
        chat_id=message.reply_to_message.chat.id,
    )

    await message.reply_text(
        (
            "<b>📢 Broadcast Ready</b>\n\n"
            "Choose the destination."
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👤 Users",
                        callback_data="broadcast#users",
                    ),
                    InlineKeyboardButton(
                        "👥 Groups",
                        callback_data="broadcast#groups",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="broadcast#cancel",
                    )
                ],
            ]
        ),
    )


async def execute_broadcast(
    client: Client,
    admin_id: int,
    target: str,
):
    """Execute a broadcast based on the saved admin state."""

    state = get_admin_state(admin_id)

    if not state:
        return False, "Broadcast session expired."

    message_id = state.get("message_id")
    source_chat_id = state.get("chat_id")

    if not message_id or not source_chat_id:
        clear_admin_state(admin_id)
        return False, "Broadcast message information is missing."

    try:
        source_message = await client.get_messages(
            source_chat_id,
            message_id,
        )
    except Exception as e:
        clear_admin_state(admin_id)
        return False, f"Could not load source message: {e}"

    clear_admin_state(admin_id)

    if target == "users":
        if not users_broadcast:
            return False, "User broadcast service is unavailable."

        if not user_db and not db:
            return False, "User database service is unavailable."

        database = user_db or db

        if not hasattr(database, "get_all_users"):
            return False, "get_all_users() is unavailable."

        success = 0
        failed = 0

        async for user in database.get_all_users():
            user_id = user.get("id")

            if not user_id:
                continue

            try:
                result = await users_broadcast(
                    user_id,
                    source_message,
                    False,
                )

                if result and result[0]:
                    success += 1
                else:
                    failed += 1

            except Exception:
                failed += 1

            await asyncio.sleep(0.05)

        return True, (
            f"Broadcast completed.\n\n"
            f"✅ Success: {success}\n"
            f"❌ Failed: {failed}"
        )

    if target == "groups":
        if not groups_broadcast:
            return False, "Group broadcast service is unavailable."

        if not group_db and not db:
            return False, "Group database service is unavailable."

        database = group_db or db

        if not hasattr(database, "get_all_chats"):
            return False, "get_all_chats() is unavailable."

        success = 0
        failed = 0

        async for group in database.get_all_chats():
            chat_id = group.get("id")

            if not chat_id:
                continue

            try:
                result = await groups_broadcast(
                    chat_id,
                    source_message,
                    False,
                )

                if result == "Success":
                    success += 1
                else:
                    failed += 1

            except Exception:
                failed += 1

            await asyncio.sleep(0.05)

        return True, (
            f"Broadcast completed.\n\n"
            f"✅ Success: {success}\n"
            f"❌ Failed: {failed}"
        )

    return False, "Unknown broadcast target."


# ============================================================================
# ADMIN CALLBACK ROUTER
# ============================================================================

@Client.on_callback_query(
    filters.regex(r"^admin#")
)
async def admin_callback_router(client: Client, query: CallbackQuery):
    """Main administrator callback router."""

    if not is_admin(query.from_user.id):
        await safe_answer(
            query,
            "⛔ You are not authorized.",
            show_alert=True,
        )
        return

    try:
        action = query.data.split("#", 1)[1]
    except Exception:
        await safe_answer(query, "Invalid action.")
        return

    if action == "home":
        await safe_answer(query)

        await safe_edit(
            query,
            (
                "<b>🛠 Administrator Panel</b>\n\n"
                "Choose an operation below."
            ),
            admin_keyboard(),
        )
        return

    if action == "close":
        await safe_answer(query)

        try:
            await query.message.delete()
        except Exception:
            pass

        return

    if action == "stats":
        await safe_answer(query)

        stats = await collect_statistics()

        await safe_edit(
            query,
            (
                "<b>📊 Bot Statistics</b>\n\n"
                f"👤 Users: <code>{format_number(stats['users'])}</code>\n"
                f"👥 Groups: <code>{format_number(stats['groups'])}</code>\n"
                f"💎 Premium: <code>{format_number(stats['premium'])}</code>"
            ),
            back_keyboard(),
        )
        return

    if action == "users":
        await safe_answer(query)

        stats = await collect_statistics()

        await safe_edit(
            query,
            (
                "<b>👥 User Management</b>\n\n"
                f"Total users: <code>{format_number(stats['users'])}</code>\n\n"
                "Use the commands below for detailed management."
            ),
            back_keyboard(),
        )
        return

    if action == "groups":
        await safe_answer(query)

        stats = await collect_statistics()

        await safe_edit(
            query,
            (
                "<b>💬 Group Management</b>\n\n"
                f"Registered groups: <code>{format_number(stats['groups'])}</code>"
            ),
            back_keyboard(),
        )
        return

    if action == "premium":
        await safe_answer(query)

        stats = await collect_statistics()

        await safe_edit(
            query,
            (
                "<b>💎 Premium Management</b>\n\n"
                f"Active premium users: "
                f"<code>{format_number(stats['premium'])}</code>\n\n"
                "<code>/addpremium USER_ID DAYS</code>\n"
                "<code>/delpremium USER_ID</code>"
            ),
            back_keyboard(),
        )
        return

    if action == "broadcast":
        await safe_answer(query)

        await safe_edit(
            query,
            (
                "<b>📢 Broadcast</b>\n\n"
                "Reply to a message and use:\n"
                "<code>/broadcast</code>"
            ),
            back_keyboard(),
        )
        return

    if action == "settings":
        await safe_answer(query)

        await safe_edit(
            query,
            (
                "<b>⚙️ Bot Settings</b>\n\n"
                "Group-specific settings should be managed through "
                "the settings service."
            ),
            back_keyboard(),
        )
        return

    if action == "maintenance":
        await safe_answer(query)

        await safe_edit(
            query,
            (
                "<b>🔧 Maintenance Mode</b>\n\n"
                "Choose an action."
            ),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Enable",
                            callback_data="maintenance#on",
                        ),
                        InlineKeyboardButton(
                            "🔴 Disable",
                            callback_data="maintenance#off",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Back",
                            callback_data="admin#home",
                        )
                    ],
                ]
            ),
        )
        return

    await safe_answer(
        query,
        "Unknown admin action.",
        show_alert=True,
    )


# ============================================================================
# MAINTENANCE CALLBACK
# ============================================================================

@Client.on_callback_query(
    filters.regex(r"^maintenance#")
)
async def maintenance_callback(client: Client, query: CallbackQuery):
    """Handle maintenance toggle callbacks."""

    if not is_admin(query.from_user.id):
        await safe_answer(
            query,
            "⛔ You are not authorized.",
            show_alert=True,
        )
        return

    try:
        action = query.data.split("#", 1)[1]
    except Exception:
        return await safe_answer(query, "Invalid action.")

    if action not in {"on", "off"}:
        return await safe_answer(query, "Invalid maintenance state.")

    enabled = action == "on"

    async with admin_operation_lock:
        updated = await set_maintenance(
            client,
            query.from_user.id,
            enabled,
        )

    if updated:
        await safe_answer(
            query,
            f"Maintenance {'enabled' if enabled else 'disabled'}.",
        )

        await safe_edit(
            query,
            (
                "<b>🔧 Maintenance Mode</b>\n\n"
                f"Current status: "
                f"<b>{'🟢 ON' if enabled else '🔴 OFF'}</b>"
            ),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🟢 Enable",
                            callback_data="maintenance#on",
                        ),
                        InlineKeyboardButton(
                            "🔴 Disable",
                            callback_data="maintenance#off",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Back",
                            callback_data="admin#home",
                        )
                    ],
                ]
            ),
        )
    else:
        await safe_answer(
            query,
            "Failed to update maintenance mode.",
            show_alert=True,
        )


# ============================================================================
# BROADCAST CALLBACK
# ============================================================================

@Client.on_callback_query(
    filters.regex(r"^broadcast#")
)
async def broadcast_callback(client: Client, query: CallbackQuery):
    """Handle broadcast destination/cancellation."""

    if not is_admin(query.from_user.id):
        await safe_answer(
            query,
            "⛔ You are not authorized.",
            show_alert=True,
        )
        return

    try:
        action = query.data.split("#", 1)[1]
    except Exception:
        return await safe_answer(query, "Invalid action.")

    if action == "cancel":
        clear_admin_state(query.from_user.id)

        await safe_answer(query, "Broadcast cancelled.")

        await safe_edit(
            query,
            "<b>❌ Broadcast cancelled.</b>",
            admin_keyboard(),
        )
        return

    if action not in {"users", "groups"}:
        return await safe_answer(
            query,
            "Invalid broadcast target.",
            show_alert=True,
        )

    state = get_admin_state(query.from_user.id)

    if not state:
        await safe_answer(
            query,
            "Broadcast session expired. Start again with /broadcast.",
            show_alert=True,
        )
        return

    target_name = "users" if action == "users" else "groups"

    await safe_answer(
        query,
        f"Starting {target_name} broadcast...",
    )

    await safe_edit(
        query,
        (
            "<b>📢 Broadcast Started</b>\n\n"
            f"Target: <code>{target_name}</code>\n\n"
            "Please wait while the broadcast is processed..."
        )
    )

    async with admin_operation_lock:
        success, result = await execute_broadcast(
            client,
            query.from_user.id,
            target_name,
        )

    if success:
        await safe_edit(
            query,
            (
                "<b>✅ Broadcast Finished</b>\n\n"
                f"{result}"
            ),
            admin_keyboard(),
        )
    else:
        await safe_edit(
            query,
            (
                "<b>❌ Broadcast Failed</b>\n\n"
                f"<code>{result}</code>"
            ),
            admin_keyboard(),
        )


# ============================================================================
# ADMIN UNKNOWN COMMAND GUARD
# ============================================================================

@Client.on_message(
    filters.private
    & filters.incoming
    & admin_only()
    & filters.command(
        [
            "admin",
            "panel",
            "adminhelp",
            "stats",
            "users",
            "groups",
            "ban",
            "unban",
            "addpremium",
            "delpremium",
            "premium",
            "maintenance",
            "broadcast",
        ]
    )
)
async def admin_command_guard(client: Client, message: Message):
    """
    Intentionally empty guard.

    Keeping this handler registered makes it easy to expand command
    permissions centrally later without changing every handler.
    """
    return


# ============================================================================
# CLEANUP
# ============================================================================

async def cleanup_admin_states():
    """
    Remove stale admin states.

    Can be called periodically from the application's background task.
    """

    now = datetime.utcnow()
    expired = []

    for user_id, state in list(admin_states.items()):
        created_at = state.get("created_at")

        if not created_at:
            expired.append(user_id)
            continue

        if now - created_at > timedelta(minutes=15):
            expired.append(user_id)

    for user_id in expired:
        clear_admin_state(user_id)


__all__ = [
    "admin_panel",
    "admin_help",
    "statistics_command",
    "users_statistics",
    "groups_statistics",
    "ban_user_command",
    "unban_user_command",
    "add_premium_command",
    "remove_premium_command",
    "premium_statistics",
    "maintenance_command",
    "broadcast_command",
    "cleanup_admin_states",
]