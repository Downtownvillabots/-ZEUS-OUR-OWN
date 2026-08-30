"""
Reusable filter keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def filter_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌐 Language",
                callback_data="filter:language",
            ),
            InlineKeyboardButton(
                "🎞 Quality",
                callback_data="filter:quality",
            ),
        ],
        [
            InlineKeyboardButton(
                "📅 Year",
                callback_data="filter:year",
            ),
            InlineKeyboardButton(
                "📁 Type",
                callback_data="filter:type",
            ),
        ],
        [
            InlineKeyboardButton(
                "📦 Size",
                callback_data="filter:size",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Reset",
                callback_data="filter:reset",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ Apply",
                callback_data="filter:apply",
            ),
        ],
    ])


def size_filter_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "< 100 MB",
                callback_data="filter:size:0-100",
            ),
        ],
        [
            InlineKeyboardButton(
                "100–500 MB",
                callback_data="filter:size:100-500",
            ),
        ],
        [
            InlineKeyboardButton(
                "500 MB–1 GB",
                callback_data="filter:size:500-1024",
            ),
        ],
        [
            InlineKeyboardButton(
                "1–2 GB",
                callback_data="filter:size:1024-2048",
            ),
        ],
        [
            InlineKeyboardButton(
                "> 2 GB",
                callback_data="filter:size:2048+",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="filter:menu",
            ),
        ],
    ])