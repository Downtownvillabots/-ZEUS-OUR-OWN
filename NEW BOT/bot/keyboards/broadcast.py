"""
Broadcast keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def broadcast_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 New Broadcast",
                callback_data="broadcast:new",
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 History",
                callback_data="broadcast:history",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="broadcast:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])


def broadcast_confirm_keyboard(
    broadcast_id: int | str,
) -> InlineKeyboardMarkup:

    broadcast_id = str(broadcast_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚀 Send Broadcast",
                callback_data=f"broadcast:send:{broadcast_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "✏️ Edit",
                callback_data=f"broadcast:edit:{broadcast_id}",
            ),
            InlineKeyboardButton(
                "🗑 Delete",
                callback_data=f"broadcast:delete:{broadcast_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="broadcast:menu",
            ),
        ],
    ])


def broadcast_progress_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⏸ Pause",
                callback_data="broadcast:pause",
            ),
            InlineKeyboardButton(
                "🛑 Stop",
                callback_data="broadcast:stop",
            ),
        ],
    ])


def broadcast_history_keyboard(
    page: int = 1,
) -> InlineKeyboardMarkup:

    page = max(1, int(page))

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"broadcast:history:page:{page - 1}"
                if page > 1
                else "noop",
            ),
            InlineKeyboardButton(
                f"📄 {page}",
                callback_data="noop",
            ),
            InlineKeyboardButton(
                "➡️",
                callback_data=f"broadcast:history:page:{page + 1}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Broadcast",
                callback_data="broadcast:menu",
            ),
        ],
    ])