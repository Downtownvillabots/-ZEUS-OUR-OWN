"""
Premium keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def premium_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💎 Plans",
                callback_data="premium:plans",
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 My Premium",
                callback_data="premium:status",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Renew",
                callback_data="premium:renew",
            ),
        ],
        [
            InlineKeyboardButton(
                "❓ FAQ",
                callback_data="premium:faq",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def premium_payment_keyboard(
    plan_id: str | int,
) -> InlineKeyboardMarkup:

    plan_id = str(plan_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💳 Pay Now",
                callback_data=f"premium:pay:{plan_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Plans",
                callback_data="premium:plans",
            ),
        ],
    ])


def premium_payment_confirm_keyboard(
    payment_id: str | int,
) -> InlineKeyboardMarkup:

    payment_id = str(payment_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Confirm Payment",
                callback_data=f"premium:payment:confirm:{payment_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"premium:payment:cancel:{payment_id}",
            ),
        ],
    ])