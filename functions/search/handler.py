"""
Search Message Handler Module.
"""
from __future__ import annotations

import re
from pyrogram import Client, filters
from pyrogram.types import Message
from app.logging import get_logger
from functions.media_indexing.database.manager import DatabaseManager

LOGGER = get_logger(__name__)


def register_search_handlers(client: Client, db_manager: DatabaseManager) -> None:
    @client.on_message(filters.text & filters.private & ~filters.command(["start", "help"]))
    async def handle_search_query(bot: Client, message: Message) -> None:
        user_query = message.text.strip()
        if not user_query:
            return

        user_id = message.from_user.id if message.from_user else 0
        LOGGER.info(f"SEARCH MESSAGE RECEIVED | user_id={user_id} | query='{user_query}'")

        # Dynamic regex construction inside the handler callback
        cleaned_query = re.escape(user_query).replace(r"\ ", r".*")
        query_pattern = {"file_name": {"$regex": cleaned_query, "$options": "i"}}

        LOGGER.info(f"SEARCH DATABASE QUERY START | Raw='{user_query}' | Pattern='{cleaned_query}'")
        
        try:
            results = await db_manager.find_in_all_shards(query_pattern, limit=50)
            
            if not results:
                LOGGER.info(f"SEARCH NO RESULTS | query='{user_query}'")
                await message.reply_text(f"❌ No files found matching **'{user_query}'**.")
                return

            LOGGER.info(f"SEARCH DATABASE QUERY FINISHED | Found={len(results)} matches")

            # Formulate response output
            reply_lines = [f"🔍 **Search Results for '{user_query}':**\n"]
            for idx, item in enumerate(results, start=1):
                file_name = item.get("file_name", "Unknown File")
                file_size = item.get("file_size_formatted", "")
                reply_lines.append(f"{idx}. `{file_name}` {f'({file_size})' if file_size else ''}")

            await message.reply_text("\n".join(reply_lines))

        except Exception as exc:
            LOGGER.error(f"Error executing search query for '{user_query}': {exc}", exc_info=True)
            await message.reply_text("⚠️ An error occurred while processing your search request.")
