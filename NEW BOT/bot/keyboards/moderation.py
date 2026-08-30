"""
Moderation keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def moderation_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚫 Banned Users",
                callback_data="moderation:banned",
            ),
        ],
        [
            InlineKeyboardButton(
                "⚠️ Reports",
                callback_data="moderation:reports",
            ),
        ],
        [
            InlineKeyboardButton(
                "🛡 Rules",
                callback_data="moderation:rules",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 Moderation Stats",
                callback_data="moderation:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin Panel",
                callback_data="admin:panel",
            ),
        ],
    ])


def moderation_user_keyboard(
    user_id: int | str,
) -> InlineKeyboardMarkup:

    user_id = str(user_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚫 Ban",
                callback_data=f"moderation:ban:{user_id}",
            ),
            InlineKeyboardButton(
                "🔇 Mute",
                callback_data=f"moderation:mute:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⚠️ Warn",
                callback_data=f"moderation:warn:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ Unban",
                callback_data=f"moderation:unban:{user_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="moderation:menu",
            ),
        ],
    ])


def moderation_confirm_keyboard(
    action: str,
    target_id: int | str,
) -> InlineKeyboardMarkup:

    action = str(action)
    target_id = str(target_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Confirm",
                callback_data=(
                    f"moderation:{action}:confirm:{target_id}"
                ),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="moderation:menu",
            ),
        ],
    ])


def report_keyboard(
    report_id: int | str,
) -> InlineKeyboardMarkup:

    report_id = str(report_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Resolve",
                callback_data=f"moderation:report:resolve:{report_id}",
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"moderation:report:reject:{report_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🚫 Ban User",
                callback_data=f"moderation:report:ban:{report_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Reports",
                callback_data="moderation:reports",
            ),
        ],
    ])