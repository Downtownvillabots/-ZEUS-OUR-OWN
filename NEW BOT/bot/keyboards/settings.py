"""
User settings keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def settings_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌐 Language",
                callback_data="settings:language",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔔 Notifications",
                callback_data="settings:notifications",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎬 Movie Preferences",
                callback_data="settings:movies",
            ),
        ],
        [
            InlineKeyboardButton(
                "📁 File Preferences",
                callback_data="settings:files",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔐 Privacy",
                callback_data="settings:privacy",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Reset Settings",
                callback_data="settings:reset",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def language_settings_keyboard() -> InlineKeyboardMarkup:

    languages = [
        ("🇬🇧 English", "en"),
        ("🇮🇳 తెలుగు", "te"),
        ("🇮🇳 हिन्दी", "hi"),
        ("🇮🇳 தமிழ்", "ta"),
        ("🇮🇳 ಕನ್ನಡ", "kn"),
        ("🇮🇳 മലയാളം", "ml"),
    ]

    rows = [
        [
            InlineKeyboardButton(
                label,
                callback_data=f"settings:language:{value}",
            ),
        ]
        for label, value in languages
    ]

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="settings:menu",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def notification_settings_keyboard(
    enabled: bool,
) -> InlineKeyboardMarkup:

    status = "ON" if enabled else "OFF"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔔 Notifications: {status}",
                callback_data="settings:notifications:toggle",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="settings:menu",
            ),
        ],
    ])