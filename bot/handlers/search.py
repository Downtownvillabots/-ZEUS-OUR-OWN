"""
bot/handlers/search.py

User search handler.

Flow:

    User sends text
          ↓
    Search Handler
          ↓
    FileSearchService
          ↓
    Ranked results
          ↓
    Telegram inline keyboard
          ↓
    Pagination / file selection

The handler does not query MongoDB directly.
"""

from __future__ import annotations

import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.services.file_search import (
    DEFAULT_PAGE_SIZE,
    SearchPage,
    SearchResult,
    file_search,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

RESULTS_PER_PAGE = DEFAULT_PAGE_SIZE

MAX_QUERY_LENGTH = 200

# Search callbacks use a compact format:
#
# search:<page>:<encoded query>
#
# Since Telegram callback_data has a size limit, long queries are stored
# server-side in the future. For now we keep the callback payload compact.


# ============================================================================
# Query helpers
# ============================================================================

def clean_user_query(
    text: Optional[str],
) -> str:
    """
    Normalize text received from Telegram.
    """

    if not text:
        return ""

    query = " ".join(
        str(text).split()
    ).strip()

    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH].strip()

    return query


# ============================================================================
# Result formatting
# ============================================================================

def format_result_line(
    index: int,
    result: SearchResult,
) -> str:
    """
    Format one search result.

    We keep the filename as the primary information because Telegram file
    names often contain quality/language/season information.
    """

    filename = (
        result.file_name
        or "Unknown File"
    )

    if result.file_size:

        size = format_size(
            result.file_size
        )

        return (
            f"<b>{index}.</b> "
            f"<code>{escape_html(filename)}</code> "
            f"<i>[{size}]</i>"
        )

    return (
        f"<b>{index}.</b> "
        f"<code>{escape_html(filename)}</code>"
    )


def escape_html(
    value: str,
) -> str:
    """
    Escape Telegram HTML characters.
    """

    value = str(
        value or ""
    )

    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_size(
    size: int,
) -> str:
    """
    Human-readable byte size.
    """

    try:
        size = float(
            size
        )
    except (
        TypeError,
        ValueError,
    ):
        return "N/A"

    if size <= 0:
        return "0 B"

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    )

    index = 0

    while (
        size >= 1024
        and index < len(units) - 1
    ):
        size /= 1024
        index += 1

    if index == 0:
        return f"{int(size)} {units[index]}"

    return (
        f"{size:.2f} {units[index]}"
    )


# ============================================================================
# Search result keyboard
# ============================================================================

def build_result_keyboard(
    page: SearchPage,
) -> InlineKeyboardMarkup:
    """
    Build result selection and pagination keyboard.
    """

    buttons = []

    start_index = (
        (page.page - 1)
        * page.page_size
    )

    for offset, result in enumerate(
        page.results
    ):

        absolute_index = (
            start_index
            + offset
            + 1
        )

        # Callback contains file id.
        #
        # Telegram callback_data must remain compact, therefore IDs are
        # converted to strings.
        callback = (
            f"fileopen:"
            f"{result.file_id}"
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"📂 {absolute_index}. "
                        f"{truncate_filename(result.file_name)}"
                    ),
                    callback_data=callback,
                )
            ]
        )

    # Pagination.
    navigation = []

    if page.has_previous:

        navigation.append(
            InlineKeyboardButton(
                "⬅️ Previous",
                callback_data=(
                    f"searchpage:"
                    f"{page.page - 1}:"
                    f"{page.query[:80]}"
                ),
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"📄 {page.page}/{page.total_pages}",
            callback_data="search_noop",
        )
    )

    if page.has_next:

        navigation.append(
            InlineKeyboardButton(
                "Next ➡️",
                callback_data=(
                    f"searchpage:"
                    f"{page.page + 1}:"
                    f"{page.query[:80]}"
                ),
            )
        )

    if navigation:
        buttons.append(
            navigation
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data="search_close",
            )
        ]
    )

    return InlineKeyboardMarkup(
        buttons
    )


def truncate_filename(
    filename: str,
    limit: int = 45,
) -> str:
    """
    Prevent huge filenames from making ugly Telegram buttons.
    """

    filename = str(
        filename or "Unknown File"
    )

    if len(filename) <= limit:
        return filename

    return (
        filename[:limit - 3]
        + "..."
    )


# ============================================================================
# Search text
# ============================================================================

def build_search_text(
    page: SearchPage,
) -> str:
    """
    Generate search-result message.
    """

    if page.total == 0:

        return (
            "<b>🔎 Search Results</b>\n\n"
            f"❌ No files found for:\n"
            f"<code>{escape_html(page.query)}</code>\n\n"
            "Try another title or a simpler search."
        )

    lines = [
        "<b>🔎 Search Results</b>",
        "",
        (
            f"Query: "
            f"<code>{escape_html(page.query)}</code>"
        ),
        (
            f"📁 Total results: "
            f"<b>{page.total}</b>"
        ),
        "",
    ]

    start_index = (
        (page.page - 1)
        * page.page_size
    )

    for offset, result in enumerate(
        page.results
    ):

        lines.append(
            format_result_line(
                start_index + offset + 1,
                result,
            )
        )

    lines.extend(
        [
            "",
            (
                f"Page "
                f"<b>{page.page}</b>"
                f"/"
                f"<b>{page.total_pages}</b>"
            ),
            "",
            "Select a file below:",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================================
# Search execution
# ============================================================================

async def execute_search(
    query: str,
) -> SearchPage:
    """
    Execute search using the service layer.
    """

    return await file_search.search_page(
        query,
        page=1,
        page_size=RESULTS_PER_PAGE,
    )


# ============================================================================
# User text search
# ============================================================================

async def search_message(
    client: Client,
    message: Message,
):
    """
    Handle normal text messages as file searches.

    Commands are excluded by the filter below.
    """

    if not message.from_user:
        return

    text = (
        message.text
        or message.caption
        or ""
    )

    query = clean_user_query(
        text
    )

    if not query:
        return

    if len(query) < 2:

        await message.reply_text(
            "🔎 Please enter at least "
            "<b>2 characters</b> to search."
        )

        return

    try:

        page = await execute_search(
            query
        )

    except Exception:
        logger.exception(
            "Search failed for user=%s query=%r",
            message.from_user.id,
            query,
        )

        await message.reply_text(
            "❌ Search failed temporarily.\n"
            "Please try again in a moment."
        )

        return

    text = build_search_text(
        page
    )

    keyboard = None

    if page.total:
        keyboard = build_result_keyboard(
            page
        )

    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================================
# Pagination
# ============================================================================

async def search_page_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Handle result pagination.
    """

    await callback_query.answer()

    data = (
        callback_query.data
        or ""
    )

    # Expected:
    #
    # searchpage:<page>:<query>

    parts = data.split(
        ":",
        2,
    )

    if len(parts) != 3:
        return

    try:
        page_number = int(
            parts[1]
        )
    except ValueError:
        return

    query = clean_user_query(
        parts[2]
    )

    if not query:
        return

    try:

        page = await file_search.search_page(
            query,
            page=page_number,
            page_size=RESULTS_PER_PAGE,
        )

    except Exception:
        logger.exception(
            "Pagination search failed"
        )

        await callback_query.answer(
            "Search failed. Try again.",
            show_alert=True,
        )

        return

    text = build_search_text(
        page
    )

    keyboard = build_result_keyboard(
        page
    )

    try:

        await callback_query.message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    except Exception:
        logger.exception(
            "Unable to update search page"
        )


# ============================================================================
# File selection
# ============================================================================

async def file_open_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Handle selection of a search result.

    The actual delivery/security/verification process belongs to
    delivery.py and verification.py.

    This callback only passes the selected file onward.
    """

    await callback_query.answer(
        "Opening file..."
    )

    data = (
        callback_query.data
        or ""
    )

    if not data.startswith(
        "fileopen:"
    ):
        return

    file_id = data[
        len("fileopen:"):
    ]

    if not file_id:
        await callback_query.answer(
            "Invalid file.",
            show_alert=True,
        )
        return

    try:

        from bot.services.delivery import (
            delivery,
        )

    except ImportError:

        await callback_query.answer(
            "File delivery is unavailable.",
            show_alert=True,
        )

        return

    handler = getattr(
        delivery,
        "handle_file_selection",
        None,
    )

    if handler is None:

        await callback_query.message.reply_text(
            "📂 File delivery is being connected."
        )

        return

    try:

        await handler(
            client=client,
            callback_query=callback_query,
            file_id=file_id,
        )

    except Exception:
        logger.exception(
            "File selection failed: %s",
            file_id,
        )

        await callback_query.message.reply_text(
            "❌ Unable to open this file."
        )


# ============================================================================
# Close search
# ============================================================================

async def close_search_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Close/delete search result message.
    """

    await callback_query.answer()

    try:

        await callback_query.message.delete()

    except Exception:
        try:

            await callback_query.message.edit_reply_markup(
                reply_markup=None
            )

        except Exception:
            pass


# ============================================================================
# No-op callback
# ============================================================================

async def noop_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Used for the page indicator button.
    """

    await callback_query.answer()


# ============================================================================
# Registration
# ============================================================================

def register(
    app: Client,
):
    """
    Explicitly register search handlers.

    This is useful if app.py uses manual handler registration.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    app.add_handler(
        MessageHandler(
            search_message,
            filters.text
            & ~filters.command(
                [
                    "start",
                    "help",
                    "settings",
                    "admin",
                    "premium",
                ]
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            search_page_callback,
            filters.regex(
                r"^searchpage:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_open_callback,
            filters.regex(
                r"^fileopen:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            close_search_callback,
            filters.regex(
                r"^search_close$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            noop_callback,
            filters.regex(
                r"^search_noop$"
            ),
        )
    )

    logger.info(
        "Registered search handlers"
    )


# ============================================================================
# Plugin-compatible handlers
# ============================================================================

@Client.on_message(
    filters.text
    & ~filters.command(
        [
            "start",
            "help",
            "settings",
            "admin",
            "premium",
        ]
    )
)
async def search_handler(
    client: Client,
    message: Message,
):
    """
    Pyrogram plugin entry point.
    """

    await search_message(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^searchpage:"
    )
)
async def search_pagination_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await search_page_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^fileopen:"
    )
)
async def file_open_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_open_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^search_close$"
    )
)
async def search_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await close_search_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^search_noop$"
    )
)
async def search_noop_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await noop_callback(
        client,
        callback_query,
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "search_message",
    "search_handler",
    "search_page_callback",
    "search_pagination_handler",
    "file_open_callback",
    "file_open_handler",
    "close_search_callback",
    "search_close_handler",
    "build_result_keyboard",
    "build_search_text",
    "execute_search",
    "register",
]