"""
Search Entry Point, Multi-Stage Callback Router, and File Delivery.
"""

from __future__ import annotations

from typing import Any
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from functions.search.config import DEFAULT_CAPTION_TEMPLATE
from functions.search.handlers.ui import (
    build_file_results_keyboard,
    build_language_keyboard,
    build_resolution_keyboard,
    build_title_selection_keyboard,
)
from functions.search.request.handlers import trigger_no_result_flow
from functions.search.services.formatters import format_bytes
from functions.search.services.query_parser import clean_search_query
from functions.search.services.session_manager import SESSION_MANAGER


def setup_search_handlers(client: Client, db_manager: Any) -> None:

    @client.on_message(filters.private & filters.text & ~filters.command(["start", "help", "index"]))
    async def handle_user_query(bot: Client, message: Message) -> None:
        user_id = message.from_user.id
        cleaned_query = clean_search_query(message.text)

        if len(cleaned_query) < 2:
            await message.reply_text("❌ Please enter a valid title to search.")
            return

        session = SESSION_MANAGER.create_session(user_id=user_id, query=cleaned_query)

        regex_query = {"$regex": cleaned_query, "$options": "i"}
        mongo_query = {
            "$or": [
                {"normalized_title": regex_query},
                {"title": regex_query},
                {"clean_name": regex_query},
            ]
        }
        
        matches = await db_manager.find_in_all_shards(mongo_query, limit=50)

        # Trigger Movie Request intelligence if 0 matches found locally
        if not matches:
            await trigger_no_result_flow(bot, message, message.text, db_manager)
            return

        unique_matches: list[dict] = []
        seen = set()
        for doc in matches:
            key = (doc.get("clean_name") or doc.get("title"), doc.get("year"))
            if key not in seen:
                seen.add(key)
                unique_matches.append(doc)

        keyboard = build_title_selection_keyboard(unique_matches, user_id=user_id)
        await message.reply_text(
            f"🏙️ **DOWNTOWN VILLA**\n\n🔎 **Search:** `{cleaned_query}`\n🎬 Select Movie Title:",
            reply_markup=keyboard,
        )

    @client.on_callback_query(filters.regex(r"^srch_"))
    async def handle_search_callbacks(bot: Client, query: CallbackQuery) -> None:
        data_parts = query.data.split("|")
        action = data_parts[0]
        
        if action == "srch_cls":
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        owner_id = int(data_parts[1])

        if query.from_user.id != owner_id:
            await query.answer("⚠️ This search session belongs to another user.", show_alert=True)
            return

        session = SESSION_MANAGER.get_session(owner_id)
        if not session:
            await query.answer("⌛ Search session expired. Please type your search again.", show_alert=True)
            try:
                await query.message.delete()
            except Exception:
                pass
            return

        if action == "srch_t":
            norm_title = data_parts[2]
            year = int(data_parts[3]) if data_parts[3] != "0" else None

            session.selected_title = norm_title
            session.selected_year = year

            match_filter: dict[str, Any] = {"normalized_title": norm_title}
            if year:
                match_filter["year"] = year

            docs = await db_manager.find_in_all_shards(match_filter, limit=100)
            languages = sorted(list({lang for d in docs for lang in d.get("languages", []) if lang}))

            if not languages:
                languages = ["unknown"]

            keyboard = build_language_keyboard(languages, user_id=owner_id)
            await query.message.edit_text(
                f"🏙️ **DOWNTOWN VILLA**\n\n🎬 **Title:** `{session.selected_title}`\n🌐 Select Language:",
                reply_markup=keyboard,
            )
            return

        if action == "srch_l":
            selected_lang = data_parts[2]
            session.selected_language = selected_lang

            match_filter = {"normalized_title": session.selected_title}
            if session.selected_year:
                match_filter["year"] = session.selected_year
            if selected_lang != "unknown":
                match_filter["languages"] = selected_lang

            docs = await db_manager.find_in_all_shards(match_filter, limit=100)
            resolutions = sorted(list({d.get("resolution") for d in docs if d.get("resolution")}))

            if not resolutions:
                resolutions = ["HD"]

            keyboard = build_resolution_keyboard(resolutions, user_id=owner_id)
            await query.message.edit_text(
                f"🏙️ **DOWNTOWN VILLA**\n\n🎬 **Title:** `{session.selected_title}`\n🌐 **Language:** `{selected_lang.capitalize()}`\n🎞️ Select Resolution:",
                reply_markup=keyboard,
            )
            return

        if action == "srch_r":
            selected_res = data_parts[2]
            session.selected_resolution = selected_res

            match_filter = {"normalized_title": session.selected_title}
            if session.selected_year:
                match_filter["year"] = session.selected_year
            if session.selected_language and session.selected_language != "unknown":
                match_filter["languages"] = session.selected_language
            if selected_res != "HD":
                match_filter["resolution"] = selected_res

            matching_files = await db_manager.find_in_all_shards(match_filter, limit=100)
            matching_files.sort(key=lambda x: int(x.get("file_size", 0)))

            keyboard = build_file_results_keyboard(matching_files, user_id=owner_id)
            await query.message.edit_text(
                f"🏙️ **DOWNTOWN VILLA**\n\n🎬 **Title:** `{session.selected_title}`\n🌐 **Language:** `{session.selected_language}`\n🎞️ **Quality:** `{selected_res}`\n\n📦 Select File Download:",
                reply_markup=keyboard,
            )
            return

        if action == "srch_f":
            file_unique_id = data_parts[2]
            matches = await db_manager.find_in_all_shards({"file_unique_id": file_unique_id}, limit=1)

            if not matches:
                await query.answer("❌ File no longer exists in index.", show_alert=True)
                return

            file_doc = matches[0]
            await query.answer("🚀 Sending file...")

            caption = DEFAULT_CAPTION_TEMPLATE.format(
                title=file_doc.get("clean_name") or file_doc.get("title") or "Unknown Movie",
                year=file_doc.get("year", "N/A"),
                language=", ".join(file_doc.get("languages", ["Unknown"])).capitalize(),
                resolution=file_doc.get("resolution", "N/A"),
                quality=file_doc.get("quality", ""),
                size_human=format_bytes(file_doc.get("file_size", 0)),
            )

            await bot.send_cached_media(
                chat_id=query.from_user.id,
                file_id=file_doc["file_id"],
                caption=caption,
            )
            SESSION_MANAGER.clear_session(owner_id)
