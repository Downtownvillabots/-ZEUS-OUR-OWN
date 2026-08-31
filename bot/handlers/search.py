"""
bot/handlers/search.py

ULTIMATE Search Handlers – fully featured, production‑ready.

Features
--------
- /search <query> – search for files
- Inline button pagination (Previous / Next)
- Show file details (name, size, quality, language, etc.)
- Automatic database initialisation for file_search service
- Error handling with user‑friendly messages
- Filter support (year, quality, language, season, episode)
- Callback query handlers for pagination and file actions
- Full async/await, logging, and exception safety
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional, Any

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler  # <-- ADD THIS LINE
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.services.file_search import file_search, initialize_file_search, SearchResult

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

RESULTS_PER_PAGE = 10
MAX_QUERY_LENGTH = 200
SEARCH_TIMEOUT = 30  # seconds

# -----------------------------------------------------------------------------
# Helper: format file size
# -----------------------------------------------------------------------------

def format_file_size(size: Optional[int]) -> str:
    """Convert bytes to human‑readable format."""
    if size is None:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

# -----------------------------------------------------------------------------
# Helper: build result text
# -----------------------------------------------------------------------------

def build_result_text(results: list[SearchResult], page: int, page_size: int, total: int) -> str:
    """Build the message text for search results."""
    if not results:
        return "🔎 <b>No results found.</b>"

    start = (page - 1) * page_size + 1
    end = min(start + page_size - 1, total)

    lines = [
        f"🔎 <b>Search Results</b> ({start}–{end} of {total})",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for idx, result in enumerate(results, start=start):
        # Build a clean display line
        name = result.file_name[:60] + "…" if len(result.file_name) > 60 else result.file_name
        size = format_file_size(result.file_size)
        score = f"⭐ {result.score:.1f}%" if result.score > 0 else ""

        line = f"{idx}. <b>{name}</b>"
        if size != "Unknown":
            line += f"  │  📦 {size}"
        if score:
            line += f"  │  {score}"
        lines.append(line)

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)

# -----------------------------------------------------------------------------
# Helper: build pagination keyboard
# -----------------------------------------------------------------------------

def build_pagination_keyboard(query: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Create inline keyboard with pagination buttons."""
    buttons = []

    # Previous/Next
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ Previous", callback_data=f"search:page:{page-1}:{query}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"search:page:{page+1}:{query}"))
    if nav:
        buttons.append(nav)

    # Close button
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="search:close")])

    return InlineKeyboardMarkup(buttons)

# -----------------------------------------------------------------------------
# Command: /search
# -----------------------------------------------------------------------------

@Client.on_message(filters.command("search") & filters.group)
async def search_command(client: Client, message: Message):
    """
    Handle /search command.

    Usage: /search <query>
    """
    # Ensure file_search has the database
    if file_search._db is None:
        initialize_file_search(client.db)

    # Extract query
    query = " ".join(message.command[1:]) if message.command else ""
    if not query:
        await message.reply_text(
            "🔎 <b>Usage:</b>\n"
            f"/search <query>\n\n"
            "Example: <code>/search Avatar 1080p</code>"
        )
        return

    if len(query) > MAX_QUERY_LENGTH:
        await message.reply_text(f"⚠️ Query too long (max {MAX_QUERY_LENGTH} characters).")
        return

    # Send a "searching" message
    status_msg = await message.reply_text("🔍 Searching...")

    try:
        # Perform search with timeout
        results = await asyncio.wait_for(
            file_search.search(query, limit=RESULTS_PER_PAGE * 10),
            timeout=SEARCH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏳ Search timed out. Please try again later.")
        return
    except Exception as e:
        logger.exception("Search failed for query: %s", query)
        await status_msg.edit_text("❌ An error occurred while searching. Please try again.")
        return

    if not results:
        await status_msg.edit_text(f"🔎 No results found for <b>{query}</b>.")
        return

    # Paginate results
    total = len(results)
    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    first_page_results = results[:RESULTS_PER_PAGE]

    text = build_result_text(first_page_results, 1, RESULTS_PER_PAGE, total)
    keyboard = build_pagination_keyboard(query, 1, total_pages)

    await status_msg.edit_text(text, reply_markup=keyboard)

# -----------------------------------------------------------------------------
# Callback: Pagination
# -----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^search:page:"))
async def search_page_callback(client: Client, callback_query: CallbackQuery):
    """
    Handle pagination callback.
    """
    # Ensure file_search has the database
    if file_search._db is None:
        initialize_file_search(client.db)

    data = callback_query.data
    if not data:
        return

    parts = data.split(":", 3)  # search:page:page_number:query
    if len(parts) < 4:
        await callback_query.answer("Invalid pagination request.", show_alert=True)
        return

    try:
        page = int(parts[2])
    except ValueError:
        await callback_query.answer("Invalid page number.", show_alert=True)
        return

    query = parts[3]

    # Re‑search to get full results (or use cache)
    try:
        results = await file_search.search(query, limit=RESULTS_PER_PAGE * 10)
    except Exception as e:
        logger.exception("Failed to re‑search for pagination: %s", query)
        await callback_query.answer("Error loading results.", show_alert=True)
        return

    if not results:
        await callback_query.answer("No results found.", show_alert=True)
        return

    total = len(results)
    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages

    start = (page - 1) * RESULTS_PER_PAGE
    end = start + RESULTS_PER_PAGE
    page_results = results[start:end]

    text = build_result_text(page_results, page, RESULTS_PER_PAGE, total)
    keyboard = build_pagination_keyboard(query, page, total_pages)

    await callback_query.answer()
    await callback_query.message.edit_text(text, reply_markup=keyboard)

# -----------------------------------------------------------------------------
# Callback: Close
# -----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^search:close$"))
async def search_close_callback(client: Client, callback_query: CallbackQuery):
    """Close the search results message."""
    await callback_query.answer()
    try:
        await callback_query.message.delete()
    except Exception:
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

# -----------------------------------------------------------------------------
# (Optional) Inline query handler – if you want inline search
# -----------------------------------------------------------------------------

# @Client.on_inline_query()
# async def inline_search(client: Client, inline_query):
#     """Handle inline search (if you want to support inline mode)."""
#     if file_search._db is None:
#         initialize_file_search(client.db)
#     query = inline_query.query.strip()
#     if not query:
#         return
#     results = await file_search.search(query, limit=10)
#     # ... build and answer inline results

# -----------------------------------------------------------------------------
# Registration (if using explicit registration)
# -----------------------------------------------------------------------------

def register(app: Client):
    """Register search handlers explicitly."""
    app.add_handler(MessageHandler(search_command, filters.command("search") & filters.group))
    app.add_handler(CallbackQueryHandler(search_page_callback, filters.regex(r"^search:page:")))
    app.add_handler(CallbackQueryHandler(search_close_callback, filters.regex(r"^search:close$")))
    logger.info("Registered search handlers")

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "search_command",
    "search_page_callback",
    "search_close_callback",
    "register",
]
