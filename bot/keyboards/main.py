"""
bot.keyboards.main

Main navigation keyboards for the Telegram bot.

The builders in this module are deliberately independent from handlers.
Handlers decide what happens; keyboards only describe what the user can click.
"""

from __future__ import annotations

from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ============================================================================
# Callback constants
# ============================================================================

CB_HOME = "nav:home"
CB_SEARCH = "nav:search"
CB_MOVIES = "nav:movies"
CB_FILES = "nav:files"
CB_PREMIUM = "nav:premium"
CB_SETTINGS = "nav:settings"
CB_HELP = "nav:help"
CB_BACK = "nav:back"

CB_ADMIN = "admin:panel"


# ============================================================================
# Main keyboard
# ============================================================================

def main_keyboard(
    *,
    is_admin: bool = False,
    show_premium: bool = True,
) -> InlineKeyboardMarkup:
    """
    Build the main user navigation keyboard.
    """

    rows = [
        [
            InlineKeyboardButton(
                "🔎 Search",
                callback_data=CB_SEARCH,
            ),
            InlineKeyboardButton(
                "🎬 Movies",
                callback_data=CB_MOVIES,
            ),
        ],
        [
            InlineKeyboardButton(
                "📁 Files",
                callback_data=CB_FILES,
            ),
            InlineKeyboardButton(
                "⚙️ Settings",
                callback_data=CB_SETTINGS,
            ),
        ],
    ]

    if show_premium:
        rows.append(
            [
                InlineKeyboardButton(
                    "💎 Premium",
                    callback_data=CB_PREMIUM,
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "❓ Help",
                callback_data=CB_HELP,
            ),
        ]
    )

    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    "🛠 Admin Panel",
                    callback_data=CB_ADMIN,
                ),
            ]
        )

    return InlineKeyboardMarkup(rows)


# ============================================================================
# Home
# ============================================================================

def home_keyboard(
    *,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:

    return main_keyboard(
        is_admin=is_admin,
    )


# ============================================================================
# Back / home
# ============================================================================

def back_keyboard(
    *,
    callback_data: str = CB_HOME,
    label: str = "⬅️ Back",
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    callback_data=callback_data,
                ),
            ],
        ]
    )


def back_home_keyboard(
    *,
    back_callback: str = CB_BACK,
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=back_callback,
                ),
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


# ============================================================================
# Search
# ============================================================================

def search_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 New Search",
                    callback_data=CB_SEARCH,
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎬 Movies",
                    callback_data=CB_MOVIES,
                ),
                InlineKeyboardButton(
                    "📁 Files",
                    callback_data=CB_FILES,
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


# ============================================================================
# Movie navigation
# ============================================================================

def movies_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search Movies",
                    callback_data="movies:search",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔥 Popular",
                    callback_data="movies:popular",
                ),
                InlineKeyboardButton(
                    "🆕 Latest",
                    callback_data="movies:latest",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎭 Genres",
                    callback_data="movies:genres",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


def movie_result_keyboard(
    movie_id: str | int,
) -> InlineKeyboardMarkup:

    movie_id = str(movie_id)

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📥 Get File",
                    callback_data=f"movie:get:{movie_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔎 Search Again",
                    callback_data=CB_SEARCH,
                ),
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


# ============================================================================
# File navigation
# ============================================================================

def files_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search Files",
                    callback_data="files:search",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📂 My Files",
                    callback_data="files:mine",
                ),
                InlineKeyboardButton(
                    "🕘 Recent",
                    callback_data="files:recent",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


def file_result_keyboard(
    file_id: str | int,
) -> InlineKeyboardMarkup:

    file_id = str(file_id)

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📥 Get File",
                    callback_data=f"file:get:{file_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑 Delete",
                    callback_data=f"file:delete:{file_id}",
                ),
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=CB_FILES,
                ),
            ],
        ]
    )


# ============================================================================
# Premium
# ============================================================================

def premium_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 View Plans",
                    callback_data="premium:plans",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 My Subscription",
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
                    "🏠 Home",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


def premium_plans_keyboard(
    plans: list[dict],
) -> InlineKeyboardMarkup:

    rows = []

    for plan in plans:

        plan_id = str(
            plan.get("id")
            or plan.get("code")
            or plan.get("name")
        )

        name = str(
            plan.get(
                "name",
                plan_id,
            )
        )

        price = plan.get(
            "price"
        )

        currency = plan.get(
            "currency",
            "",
        )

        if price is not None:
            label = (
                f"💎 {name} — "
                f"{price} {currency}"
            ).strip()
        else:
            label = f"💎 {name}"

        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=(
                        f"premium:plan:{plan_id}"
                    ),
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=CB_PREMIUM,
            ),
        ]
    )

    return InlineKeyboardMarkup(rows)


# ============================================================================
# Settings
# ============================================================================

def settings_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🌐 Language",
                    callback_data="settings:language",
                ),
                InlineKeyboardButton(
                    "🔔 Notifications",
                    callback_data="settings:notifications",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎬 Movie Settings",
                    callback_data="settings:movies",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📁 File Settings",
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
                    "⬅️ Back",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


# ============================================================================
# Help
# ============================================================================

def help_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📖 How to Use",
                    callback_data="help:guide",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔎 Search Help",
                    callback_data="help:search",
                ),
                InlineKeyboardButton(
                    "📁 File Help",
                    callback_data="help:files",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💎 Premium FAQ",
                    callback_data="help:premium",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data=CB_HOME,
                ),
            ],
        ]
    )


# ============================================================================
# Confirmation
# ============================================================================

def confirmation_keyboard(
    confirm_callback: str,
    cancel_callback: str = CB_BACK,
    *,
    confirm_label: str = "✅ Confirm",
    cancel_label: str = "❌ Cancel",
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    confirm_label,
                    callback_data=confirm_callback,
                ),
                InlineKeyboardButton(
                    cancel_label,
                    callback_data=cancel_callback,
                ),
            ],
        ]
    )


# ============================================================================
# Pagination
# ============================================================================

def pagination_keyboard(
    *,
    page: int,
    total_pages: int,
    callback_prefix: str,
    back_callback: str = CB_HOME,
) -> InlineKeyboardMarkup:

    page = max(
        1,
        int(page),
    )

    total_pages = max(
        1,
        int(total_pages),
    )

    page = min(
        page,
        total_pages,
    )

    buttons = []

    if page > 1:

        buttons.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=(
                    f"{callback_prefix}:page:{page - 1}"
                ),
            )
        )

    buttons.append(
        InlineKeyboardButton(
            f"📄 {page}/{total_pages}",
            callback_data="noop",
        )
    )

    if page < total_pages:

        buttons.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=(
                    f"{callback_prefix}:page:{page + 1}"
                ),
            )
        )

    rows = [buttons]

    rows.append(
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data=back_callback,
            ),
        ]
    )

    return InlineKeyboardMarkup(rows)


# ============================================================================
# Generic menu
# ============================================================================

def menu_keyboard(
    items: list[tuple[str, str]],
    *,
    columns: int = 2,
    back_callback: Optional[str] = CB_HOME,
) -> InlineKeyboardMarkup:

    columns = max(
        1,
        min(
            int(columns),
            4,
        ),
    )

    rows = []
    current = []

    for label, callback in items:

        current.append(
            InlineKeyboardButton(
                str(label),
                callback_data=str(callback),
            )
        )

        if len(current) >= columns:

            rows.append(current)
            current = []

    if current:
        rows.append(current)

    if back_callback is not None:

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=back_callback,
                ),
            ]
        )

    return InlineKeyboardMarkup(rows)


# ============================================================================
# Safe callback helper
# ============================================================================

def callback_button(
    label: str,
    callback_data: str,
) -> InlineKeyboardButton:

    if len(callback_data.encode("utf-8")) > 64:
        raise ValueError(
            "Telegram callback_data must not exceed 64 bytes."
        )

    return InlineKeyboardButton(
        text=str(label),
        callback_data=str(callback_data),
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CB_HOME",
    "CB_SEARCH",
    "CB_MOVIES",
    "CB_FILES",
    "CB_PREMIUM",
    "CB_SETTINGS",
    "CB_HELP",
    "CB_BACK",
    "CB_ADMIN",

    "main_keyboard",
    "home_keyboard",

    "back_keyboard",
    "back_home_keyboard",

    "search_keyboard",

    "movies_keyboard",
    "movie_result_keyboard",

    "files_keyboard",
    "file_result_keyboard",

    "premium_keyboard",
    "premium_plans_keyboard",

    "settings_keyboard",
    "help_keyboard",

    "confirmation_keyboard",
    "pagination_keyboard",
    "menu_keyboard",

    "callback_button",
]