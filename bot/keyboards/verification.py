"""
Verification keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def verification_keyboard(
    verification_url: str | None = None,
) -> InlineKeyboardMarkup:

    rows = []

    if verification_url:

        rows.append([
            InlineKeyboardButton(
                "🔐 Verify",
                url=verification_url,
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            "✅ Check Verification",
            callback_data="verification:check",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def verification_retry_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 Check Again",
                callback_data="verification:check",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])