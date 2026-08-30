"""
Search keyboards.

All callbacks use the search:* namespace.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def search_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Search",
                callback_data="search:new",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎛 Filters",
                callback_data="search:filters",
            ),
            InlineKeyboardButton(
                "↕️ Sort",
                callback_data="search:sort",
            ),
        ],
        [
            InlineKeyboardButton(
                "🧹 Clear",
                callback_data="search:clear",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def search_filter_keyboard(
    *,
    language: str | None = None,
    quality: str | None = None,
    year: str | None = None,
    file_type: str | None = None,
) -> InlineKeyboardMarkup:

    language = language or "Any"
    quality = quality or "Any"
    year = year or "Any"
    file_type = file_type or "Any"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🌐 Language: {language}",
                callback_data="search:filter:language",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🎞 Quality: {quality}",
                callback_data="search:filter:quality",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📅 Year: {year}",
                callback_data="search:filter:year",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📁 Type: {file_type}",
                callback_data="search:filter:type",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 Reset Filters",
                callback_data="search:filters:reset",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="search:menu",
            ),
        ],
    ])


def language_keyboard() -> InlineKeyboardMarkup:

    languages = [
        ("🌐 Any", "any"),
        ("🇬🇧 English", "english"),
        ("🇮🇳 Hindi", "hindi"),
        ("🇮🇳 Telugu", "telugu"),
        ("🇮🇳 Tamil", "tamil"),
        ("🇮🇳 Malayalam", "malayalam"),
        ("🇮🇳 Kannada", "kannada"),
        ("🇧🇩 Bengali", "bengali"),
    ]

    rows = [
        [
            InlineKeyboardButton(
                label,
                callback_data=f"search:language:{value}",
            ),
        ]
        for label, value in languages
    ]

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="search:filters",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def quality_keyboard() -> InlineKeyboardMarkup:

    qualities = [
        ("Any", "any"),
        ("CAM", "cam"),
        ("480p", "480p"),
        ("720p", "720p"),
        ("1080p", "1080p"),
        ("2160p / 4K", "2160p"),
    ]

    rows = []

    for label, value in qualities:
        rows.append([
            InlineKeyboardButton(
                label,
                callback_data=f"search:quality:{value}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="search:filters",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def year_keyboard() -> InlineKeyboardMarkup:

    rows = [
        [
            InlineKeyboardButton(
                "Any Year",
                callback_data="search:year:any",
            ),
        ],
        [
            InlineKeyboardButton(
                "2026",
                callback_data="search:year:2026",
            ),
            InlineKeyboardButton(
                "2025",
                callback_data="search:year:2025",
            ),
        ],
        [
            InlineKeyboardButton(
                "2024",
                callback_data="search:year:2024",
            ),
            InlineKeyboardButton(
                "2023",
                callback_data="search:year:2023",
            ),
        ],
        [
            InlineKeyboardButton(
                "2020–2022",
                callback_data="search:year:2020-2022",
            ),
        ],
        [
            InlineKeyboardButton(
                "Older",
                callback_data="search:year:older",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="search:filters",
            ),
        ],
    ]

    return InlineKeyboardMarkup(rows)


def file_type_keyboard() -> InlineKeyboardMarkup:

    types = [
        ("📦 Any", "any"),
        ("🎬 Video", "video"),
        ("🎵 Audio", "audio"),
        ("📄 Document", "document"),
        ("🖼 Image", "image"),
        ("📚 Archive", "archive"),
    ]

    rows = [
        [
            InlineKeyboardButton(
                label,
                callback_data=f"search:type:{value}",
            ),
        ]
        for label, value in types
    ]

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="search:filters",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def sort_keyboard(
    current: str | None = None,
) -> InlineKeyboardMarkup:

    current = current or "relevance"

    options = [
        ("🎯 Relevance", "relevance"),
        ("🆕 Newest", "newest"),
        ("🕐 Oldest", "oldest"),
        ("🔤 Name A–Z", "name_asc"),
        ("🔤 Name Z–A", "name_desc"),
        ("📦 Largest", "size_desc"),
        ("📦 Smallest", "size_asc"),
    ]

    rows = []

    for label, value in options:

        prefix = "✅ " if value == current else ""

        rows.append([
            InlineKeyboardButton(
                prefix + label,
                callback_data=f"search:sort:{value}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="search:menu",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def search_results_keyboard(
    *,
    page: int,
    total_pages: int,
    query: str = "",
) -> InlineKeyboardMarkup:

    page = max(1, int(page))
    total_pages = max(1, int(total_pages))
    page = min(page, total_pages)

    rows = []

    navigation = []

    if page > 1:
        navigation.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=f"search:page:{page - 1}",
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"📄 {page}/{total_pages}",
            callback_data="noop",
        )
    )

    if page < total_pages:
        navigation.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=f"search:page:{page + 1}",
            )
        )

    rows.append(navigation)

    rows.append([
        InlineKeyboardButton(
            "🎛 Filters",
            callback_data="search:filters",
        ),
        InlineKeyboardButton(
            "↕️ Sort",
            callback_data="search:sort",
        ),
    ])

    rows.append([
        InlineKeyboardButton(
            "🔎 New Search",
            callback_data="search:new",
        ),
    ])

    rows.append([
        InlineKeyboardButton(
            "🏠 Home",
            callback_data="nav:home",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def search_result_item_keyboard(
    result_id: str | int,
) -> InlineKeyboardMarkup:

    result_id = str(result_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 Get",
                callback_data=f"search:get:{result_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Results",
                callback_data="search:results",
            ),
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])