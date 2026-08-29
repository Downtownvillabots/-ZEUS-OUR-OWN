"""
Interactive Guided Multi-Step Telegram UI Handler.
"""

from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from functions.search.services.formatters import format_bytes


def build_title_selection_keyboard(matches: list[dict], user_id: int, page: int = 1, page_size: int = 5) -> InlineKeyboardMarkup:
    """Stage 1: Movie title selection keyboard."""
    buttons = []
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paged_matches = matches[start_idx:end_idx]

    for item in paged_matches:
        title = item.get("clean_name") or item.get("title") or "Unknown"
        year = item.get("year")
        label = f"🎬 {title} • {year}" if year else f"🎬 {title}"
        cb_data = f"srch_t|{user_id}|{item.get('normalized_title')}|{year or 0}"
        buttons.append([InlineKeyboardButton(label, callback_data=cb_data[:64])])

    total_pages = max(1, (len(matches) + page_size - 1) // page_size)
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"srch_tp|{user_id}|{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="srch_noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"srch_tp|{user_id}|{page + 1}"))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🗑️ Close", callback_data=f"srch_cls|{user_id}")])
    return InlineKeyboardMarkup(buttons)


def build_language_keyboard(languages: list[str], user_id: int) -> InlineKeyboardMarkup:
    """Stage 2: Available language selection keyboard."""
    buttons = []
    flag_map = {"tamil": "🇮🇳", "malayalam": "🇮🇳", "telugu": "🇮🇳", "hindi": "🇮🇳", "english": "🇬🇧", "kannada": "🇮🇳"}

    row = []
    for lang in languages:
        flag = flag_map.get(lang.lower(), "🌐")
        label = f"{flag} {lang.capitalize()}"
        cb_data = f"srch_l|{user_id}|{lang}"
        row.append(InlineKeyboardButton(label, callback_data=cb_data[:64]))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🗑️ Close", callback_data=f"srch_cls|{user_id}")])
    return InlineKeyboardMarkup(buttons)


def build_resolution_keyboard(resolutions: list[str], user_id: int) -> InlineKeyboardMarkup:
    """Stage 3: Available resolution selection keyboard."""
    buttons = []
    icon_map = {"2160p": "🔥", "4k": "🔥", "1080p": "📺", "720p": "📺", "480p": "📱", "360p": "📱"}

    row = []
    for res in resolutions:
        icon = icon_map.get(res.lower(), "🎞️")
        label = f"{icon} {res}"
        cb_data = f"srch_r|{user_id}|{res}"
        row.append(InlineKeyboardButton(label, callback_data=cb_data[:64]))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🗑️ Close", callback_data=f"srch_cls|{user_id}")])
    return InlineKeyboardMarkup(buttons)


def build_file_results_keyboard(files: list[dict], user_id: int) -> InlineKeyboardMarkup:
    """Stage 4: File size selection keyboard (Sorted Ascending)."""
    buttons = []
    for item in files:
        size_bytes = item.get("file_size", 0)
        size_str = format_bytes(size_bytes)
        res = item.get("resolution", "")
        label = f"📦 {size_str} • {res}" if res else f"📦 {size_str}"
        cb_data = f"srch_f|{user_id}|{item['file_unique_id']}"
        buttons.append([InlineKeyboardButton(label, callback_data=cb_data[:64])])

    buttons.append([InlineKeyboardButton("🗑️ Close", callback_data=f"srch_cls|{user_id}")])
    return InlineKeyboardMarkup(buttons)
