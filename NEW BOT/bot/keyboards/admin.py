"""
Admin panel keyboards.

Callbacks use the admin:* namespace.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 Users",
                callback_data="admin:users",
            ),
            InlineKeyboardButton(
                "📁 Files",
                callback_data="admin:files",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎬 Movies",
                callback_data="admin:movies",
            ),
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="admin:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin:broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "🛡 Moderation",
                callback_data="admin:moderation",
            ),
            InlineKeyboardButton(
                "⚙️ Settings",
                callback_data="admin:settings",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def admin_users_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Search User",
                callback_data="admin:user:search",
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 List Users",
                callback_data="admin:user:list",
            ),
            InlineKeyboardButton(
                "💎 Premium Users",
                callback_data="admin:user:premium",
            ),
        ],
        [
            InlineKeyboardButton(
                "🚫 Banned Users",
                callback_data="admin:user:banned",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])


def admin_user_actions_keyboard(
    user_id: int | str,
    *,
    is_banned: bool = False,
    is_premium: bool = False,
) -> InlineKeyboardMarkup:

    user_id = str(user_id)

    rows = [
        [
            InlineKeyboardButton(
                "ℹ️ Details",
                callback_data=f"admin:user:info:{user_id}",
            ),
        ],
    ]

    if is_banned:
        rows.append([
            InlineKeyboardButton(
                "✅ Unban",
                callback_data=f"admin:user:unban:{user_id}",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                "🚫 Ban",
                callback_data=f"admin:user:ban:{user_id}",
            ),
        ])

    if is_premium:
        rows.append([
            InlineKeyboardButton(
                "💎 Manage Premium",
                callback_data=f"admin:user:premium:{user_id}",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                "💎 Give Premium",
                callback_data=f"admin:user:premium:{user_id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Users",
            callback_data="admin:users",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 User Stats",
                callback_data="admin:stats:users",
            ),
            InlineKeyboardButton(
                "📁 File Stats",
                callback_data="admin:stats:files",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔎 Search Stats",
                callback_data="admin:stats:search",
            ),
            InlineKeyboardButton(
                "💎 Premium Stats",
                callback_data="admin:stats:premium",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="admin:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])


def admin_files_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Search Files",
                callback_data="admin:file:search",
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 List Files",
                callback_data="admin:file:list",
            ),
            InlineKeyboardButton(
                "🗑 Deleted",
                callback_data="admin:file:deleted",
            ),
        ],
        [
            InlineKeyboardButton(
                "⏰ Expired",
                callback_data="admin:file:expired",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⚙️ Bot Settings",
                callback_data="admin:settings:bot",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔎 Search Settings",
                callback_data="admin:settings:search",
            ),
        ],
        [
            InlineKeyboardButton(
                "💎 Premium Settings",
                callback_data="admin:settings:premium",
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 Broadcast Settings",
                callback_data="admin:settings:broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])