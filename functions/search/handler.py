"""
User Search, Dynamic Pagination, and Cached Media Delivery Handler.
Diagnosed & Repaired for DOWNTOWN VILLA.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.logging import get_logger
from functions.media_indexing.database.manager import DatabaseManager
from functions.search.config import AUTO_DELETE_SECONDS, MIN_QUERY_LENGTH, PAGE_SIZE

LOGGER = get_logger(__name__)


def normalize_query_string(raw_query: str) -> str:
    """Cleans input search query, converting spaces/punctuation to flexible regex patterns."""
    clean = raw_query.strip()
    # Remove excessive spaces
    clean = re.sub(r"\s+", " ", clean)
    # Escape special regex characters
    escaped = re.escape(clean)
    # Allow spaces to match dots, underscores, hyphens, or spaces
    flexible_pattern = escaped.replace(r"\ ", r"[\s._-]+")
    return flexible_pattern


class SearchHandler:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    async def search_media(self, query_text: str, page: int = 1) -> tuple[list[dict[str, Any]], int]:
        """Executes search across all media database shards using normalized schema fields."""
        pattern = normalize_query_string(query_text)
        LOGGER.info("SEARCH DATABASE QUERY START | Raw='%.15s...' | Pattern='%s'", query_text, pattern)

        regex_query = {"$regex": pattern, "$options": "i"}
        mongo_query = {
            "$or": [
                {"title": regex_query},
                {"normalized_title": regex_query},
                {"clean_name": regex_query},
                {"original_name": regex_query},
                {"caption": regex_query},
            ]
        }

        try:
            raw_results = await self.db_manager.find_in_all_shards(mongo_query, limit=100)
            LOGGER.info("SEARCH DATABASE QUERY FINISHED | Found=%d matches", len(raw_results))
        except Exception as exc:
            LOGGER.exception("SEARCH DATABASE ERROR | Query='%.15s...': %s", query_text, exc)
            return [], 0

        total_results = len(raw_results)
        start_idx = (page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        paged_results = raw_results[start_idx:end_idx]

        return paged_results, total_results

    async def auto_delete_task(self, *messages: Message) -> None:
        """Background task to remove search results after configured duration."""
        await asyncio.sleep(AUTO_DELETE_SECONDS)
        for msg in messages:
            try:
                await msg.delete()
            except Exception as exc:
                LOGGER.debug("Auto-delete cleanup notice: %s", exc)


def register_search_handlers(client: Client, db_manager: DatabaseManager) -> None:
    LOGGER.info("SEARCH MESSAGE HANDLER REGISTERING...")
    handler = SearchHandler(db_manager)

    @client.on_message(filters.private & filters.text & ~filters.command(["start", "help", "index"]))
    async def handle_user_search(bot: Client, message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        raw_text = message.text.strip() if message.text else ""

        LOGGER.info("SEARCH MESSAGE RECEIVED | user_id=%d | query='%s'", user_id, raw_text)

        if len(raw_text) < MIN_QUERY_LENGTH:
            LOGGER.warning("SEARCH QUERY REJECTED | Reason=Too short (%d chars)", len(raw_text))
            await message.reply_text("❌ Please enter at least 2 characters to search.")
            return

        try:
            results, total = await handler.search_media(raw_text, page=1)

            if not results:
                LOGGER.info("SEARCH NO RESULTS | query='%s'", raw_text)
                reply = await message.reply_text(
                    f"🔍 **No results found for:** `{raw_text}`\n\n"
                    "💡 *Try searching with a single keyword or checking the spelling.*"
                )
                asyncio.create_task(handler.auto_delete_task(message, reply))
                return

            LOGGER.info("SEARCH RESULTS | query='%s' | total=%d | page_items=%d", raw_text, total, len(results))

            text = f"🔍 **Search Results for:** `{raw_text}`\n📊 **Total Found:** {total}\n\n"
            buttons = []

            for idx, item in enumerate(results, 1):
                title = item.get("clean_name") or item.get("title") or item.get("original_name") or "Unknown File"
                year = f" ({item.get('year')})" if item.get("year") else ""
                size_mb = item.get("file_size", 0) / (1024 * 1024)
                res = f"[{item.get('resolution')}]" if item.get("resolution") else ""

                text += f"**{idx}.** `{title}{year}`\n💾 `{size_mb:.1f} MB` {res}\n\n"
                buttons.append([InlineKeyboardButton(f"📥 Get File #{idx}", callback_data=f"src_get|{item['file_unique_id']}")])

            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            nav_row = []
            if total_pages > 1:
                nav_row.append(InlineKeyboardButton(f"📄 1/{total_pages}", callback_data="src_noop"))
                nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"src_p|2|{raw_text[:15]}"))
                buttons.append(nav_row)

            buttons.append([InlineKeyboardButton("🗑️ Close", callback_data="src_close")])

            reply = await message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=True,
            )
            asyncio.create_task(handler.auto_delete_task(message, reply))

        except Exception as exc:
            LOGGER.exception("FATAL ERROR IN SEARCH HANDLER | user_id=%d | query='%s': %s", user_id, raw_text, exc)
            await message.reply_text("⚠️ An error occurred while processing your search. Please try again later.")

    @client.on_callback_query(filters.regex(r"^src_get\|"))
    async def handle_file_delivery(bot: Client, query: CallbackQuery) -> None:
        file_unique_id = query.data.split("|")[1]
        LOGGER.info("SEARCH FILE DELIVERY REQUESTED | file_unique_id=%s", file_unique_id)

        try:
            matches = await db_manager.find_in_all_shards({"file_unique_id": file_unique_id}, limit=1)

            if not matches:
                await query.answer("❌ File no longer exists in index.", show_alert=True)
                return

            file_doc = matches[0]
            await query.answer("Sending file...")
            sent_msg = await bot.send_cached_media(
                chat_id=query.from_user.id,
                file_id=file_doc["file_id"],
                caption=f"🎬 **{file_doc.get('clean_name') or file_doc.get('title')}**\n\n🏙️ *Downtown Villa Media*",
            )
            asyncio.create_task(handler.auto_delete_task(sent_msg))
        except Exception as exc:
            LOGGER.exception("ERROR DELIVERING FILE | file_unique_id=%s: %s", file_unique_id, exc)
            await query.answer("❌ Failed to deliver file.", show_alert=True)

    @client.on_callback_query(filters.regex(r"^src_close$"))
    async def handle_close(bot: Client, query: CallbackQuery) -> None:
        try:
            await query.message.delete()
        except Exception:
            pass

    LOGGER.info("SEARCH MESSAGE HANDLER REGISTERED SUCCESSFUL")
