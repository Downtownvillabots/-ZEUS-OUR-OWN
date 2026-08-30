"""
Common keyboard helpers.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def back_keyboard(
    callback: str = "nav:home",
    label: str = "⬅️ Back",
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                label,
                callback_data=callback,
            ),
        ],
    ])


def back_home_keyboard(
    back_callback: str = "nav:back",
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=back_callback,
            ),
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def confirm_keyboard(
    confirm_callback: str,
    cancel_callback: str = "nav:back",
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Confirm",
                callback_data=confirm_callback,
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=cancel_callback,
            ),
        ],
    ])


def noop_button(
    label: str,
) -> InlineKeyboardButton:

    return InlineKeyboardButton(
        label,
        callback_data="noop",
    )


def single_button(
    label: str,
    callback: str,
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                label,
                callback_data=callback,
            ),
        ],
    ])