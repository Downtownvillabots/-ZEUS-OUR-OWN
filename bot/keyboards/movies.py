"""
Movie-specific keyboards.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def movie_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔎 Search Movies",
                callback_data="movie:search",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔥 Popular",
                callback_data="movie:popular",
            ),
            InlineKeyboardButton(
                "🆕 Latest",
                callback_data="movie:latest",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎭 Genres",
                callback_data="movie:genres",
            ),
            InlineKeyboardButton(
                "📅 By Year",
                callback_data="movie:years",
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])


def movie_genres_keyboard() -> InlineKeyboardMarkup:

    genres = [
        ("🎬 Action", "action"),
        ("😂 Comedy", "comedy"),
        ("❤️ Romance", "romance"),
        ("👻 Horror", "horror"),
        ("🧠 Thriller", "thriller"),
        ("🚀 Sci-Fi", "science_fiction"),
        ("🧙 Fantasy", "fantasy"),
        ("🎭 Drama", "drama"),
        ("🕵️ Crime", "crime"),
        ("🌍 Adventure", "adventure"),
    ]

    rows = []

    for index in range(0, len(genres), 2):

        pair = genres[index:index + 2]

        rows.append([
            InlineKeyboardButton(
                label,
                callback_data=f"movie:genre:{value}",
            )
            for label, value in pair
        ])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data="movie:menu",
        ),
    ])

    return InlineKeyboardMarkup(rows)


def movie_years_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "2026",
                callback_data="movie:year:2026",
            ),
            InlineKeyboardButton(
                "2025",
                callback_data="movie:year:2025",
            ),
        ],
        [
            InlineKeyboardButton(
                "2024",
                callback_data="movie:year:2024",
            ),
            InlineKeyboardButton(
                "2023",
                callback_data="movie:year:2023",
            ),
        ],
        [
            InlineKeyboardButton(
                "2020–2022",
                callback_data="movie:year:2020-2022",
            ),
            InlineKeyboardButton(
                "2010–2019",
                callback_data="movie:year:2010-2019",
            ),
        ],
        [
            InlineKeyboardButton(
                "Before 2010",
                callback_data="movie:year:before-2010",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="movie:menu",
            ),
        ],
    ])


def movie_result_keyboard(
    movie_id: str | int,
) -> InlineKeyboardMarkup:

    movie_id = str(movie_id)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📥 Get Movie",
                callback_data=f"movie:get:{movie_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔎 Find Files",
                callback_data=f"movie:files:{movie_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data="movie:menu",
            ),
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="nav:home",
            ),
        ],
    ])