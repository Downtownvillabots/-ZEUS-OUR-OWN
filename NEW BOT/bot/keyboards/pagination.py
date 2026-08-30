"""
Generic pagination keyboard builders.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def pagination_keyboard(
    *,
    page: int,
    total_pages: int,
    callback_prefix: str,
    back_callback: str = "nav:home",
) -> InlineKeyboardMarkup:

    page = max(1, int(page))
    total_pages = max(1, int(total_pages))

    page = min(page, total_pages)

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

    return InlineKeyboardMarkup([
        buttons,
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data=back_callback,
            ),
        ],
    ])


def compact_pagination_keyboard(
    *,
    page: int,
    total_pages: int,
    callback_prefix: str,
) -> InlineKeyboardMarkup:

    page = max(1, int(page))
    total_pages = max(1, int(total_pages))

    page = min(page, total_pages)

    row = []

    if page > 1:
        row.append(
            InlineKeyboardButton(
                "◀️",
                callback_data=(
                    f"{callback_prefix}:page:{page - 1}"
                ),
            )
        )

    row.append(
        InlineKeyboardButton(
            f"{page}/{total_pages}",
            callback_data="noop",
        )
    )

    if page < total_pages:
        row.append(
            InlineKeyboardButton(
                "▶️",
                callback_data=(
                    f"{callback_prefix}:page:{page + 1}"
                ),
            )
        )

    return InlineKeyboardMarkup([row])


def numbered_pagination_keyboard(
    *,
    page: int,
    total_pages: int,
    callback_prefix: str,
    window: int = 2,
) -> InlineKeyboardMarkup:

    page = max(1, int(page))
    total_pages = max(1, int(total_pages))
    window = max(1, int(window))

    page = min(page, total_pages)

    start = max(
        1,
        page - window,
    )

    end = min(
        total_pages,
        page + window,
    )

    row = []

    if start > 1:

        row.append(
            InlineKeyboardButton(
                "1",
                callback_data=f"{callback_prefix}:page:1",
            )
        )

        if start > 2:

            row.append(
                InlineKeyboardButton(
                    "…",
                    callback_data="noop",
                )
            )

    for number in range(
        start,
        end + 1,
    ):

        label = (
            f"✅ {number}"
            if number == page
            else str(number)
        )

        callback = (
            "noop"
            if number == page
            else f"{callback_prefix}:page:{number}"
        )

        row.append(
            InlineKeyboardButton(
                label,
                callback_data=callback,
            )
        )

    if end < total_pages:

        if end < total_pages - 1:

            row.append(
                InlineKeyboardButton(
                    "…",
                    callback_data="noop",
                )
            )

        row.append(
            InlineKeyboardButton(
                str(total_pages),
                callback_data=(
                    f"{callback_prefix}:page:{total_pages}"
                ),
            )
        )

    return InlineKeyboardMarkup([
        row,
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])