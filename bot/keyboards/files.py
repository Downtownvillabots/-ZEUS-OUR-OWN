"""
File navigation keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def file_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Search Files",
                callback_data="file:search",
            ),
        ],
        [
            InlineKeyboardButton(
                "📂 My Files",
                callback_data="file:mine",
            ),
            InlineKeyboardButton(
                "🕘 Recent",
                callback_data="file:recent",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="file:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def file_actions_keyboard(
    file_id: str | int,
) -> InlineKeyboardMarkup:

    file_id = str(file_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 Download",
                callback_data=f"file:get:{file_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Details",
                callback_data=f"file:info:{file_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"file:delete:{file_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="file:menu",
            ),
        ],
    ])


def file_confirm_delete_keyboard(
    file_id: str | int,
) -> InlineKeyboardMarkup:

    file_id = str(file_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Yes, Delete",
                callback_data=f"file:delete:confirm:{file_id}",
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"file:info:{file_id}",
            ),
        ],
    ])