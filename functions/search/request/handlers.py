"""
Movie Request UI, BIN Dispatcher, Admin Fulfillment, and User Notification Handler.
"""

from __future__ import annotations

from typing import Any
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from functions.search.request.config import ADMIN_USER_IDS, REQUEST_BIN_CHANNEL_ID
from functions.search.request.imdb import fetch_imdb_metadata
from functions.search.request.models import MovieRequest, RequestStatus
from functions.search.request.repository import RequestRepository
from functions.search.request.spell import find_fuzzy_suggestion, normalize_title_query


async def trigger_no_result_flow(bot: Client, message: Message, raw_query: str, db_manager: Any) -> None:
    clean_title, year, language = normalize_title_query(raw_query)

    all_indexed_docs = await db_manager.find_in_all_shards({}, limit=200)
    candidate_titles = list({d.get("clean_name") or d.get("title") for d in all_indexed_docs if d.get("title")})
    suggestion = find_fuzzy_suggestion(clean_title, candidate_titles)

    buttons = []
    if suggestion:
        buttons.append([InlineKeyboardButton(f"🔎 Did you mean: {suggestion}?", callback_data=f"req_sug|{suggestion}")])

    buttons.append([InlineKeyboardButton("📝 Request This Movie", callback_data=f"req_create|{message.from_user.id}")])
    buttons.append([InlineKeyboardButton("🗑️ Close", callback_data="srch_cls")])

    text = (
        f"❌ **No direct results found for:** `{raw_query}`\n\n"
        f"🎬 **Normalized Title:** `{clean_title}`\n"
        f"📅 **Year:** `{year or 'Unknown'}`\n"
        f"🌐 **Language:** `{language.capitalize() if language else 'Any'}`\n\n"
        f"Would you like to submit a request to our admins?"
    )
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


def setup_request_handlers(client: Client, db_manager: Any) -> None:
    repo = RequestRepository(db_manager)

    @client.on_callback_query(filters.regex(r"^req_create\|"))
    async def handle_create_request_callback(bot: Client, query: CallbackQuery) -> None:
        user = query.from_user
        raw_query = query.message.text.split("`")[1] if "`" in query.message.text else query.message.text
        clean_title, year, language = normalize_title_query(raw_query)

        await query.answer("Fetching IMDb data & creating request...", show_alert=False)

        imdb_data = await fetch_imdb_metadata(clean_title, year)
        req_id = await repo.get_next_request_id()

        movie_req = MovieRequest(
            request_id=req_id,
            user_id=user.id,
            username=user.username,
            display_name=f"{user.first_name} {user.last_name or ''}".strip(),
            original_query=raw_query,
            normalized_query=clean_title,
            title=imdb_data.get("title") if imdb_data else clean_title,
            year=int(imdb_data["year"]) if (imdb_data and imdb_data.get("year", "").isdigit()) else year,
            language=language,
            imdb_id=imdb_data.get("imdb_id") if imdb_data else None,
            imdb_title=imdb_data.get("title") if imdb_data else None,
        )

        if REQUEST_BIN_CHANNEL_ID != 0:
            bin_text = (
                f"🏙️ **DOWNTOWN VILLA — NEW MOVIE REQUEST**\n\n"
                f"🔢 **Request ID:** `{movie_req.request_id}`\n"
                f"🎬 **Requested Title:** `{movie_req.title}`\n"
                f"📅 **Year:** `{movie_req.year or 'N/A'}`\n"
                f"🌐 **Language:** `{movie_req.language or 'Any'}`\n"
                f"👤 **User:** {movie_req.display_name} (`{movie_req.user_id}`)\n"
                f"🔗 **Username:** @{movie_req.username or 'None'}\n"
                f"🎬 **IMDb:** {movie_req.imdb_id or 'Not Found'}\n\n"
                f"🟡 **STATUS: PENDING**"
            )
            admin_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ MOVIE UPLOADED", callback_data=f"req_ful|{movie_req.request_id}")]
            ])
            try:
                msg = await bot.send_message(REQUEST_BIN_CHANNEL_ID, bin_text, reply_markup=admin_markup)
                movie_req.request_channel_id = REQUEST_BIN_CHANNEL_ID
                movie_req.request_message_id = msg.id
            except Exception:
                pass

        await repo.create_request(movie_req)

        await query.message.edit_text(
            f"✅ **Request Submitted!**\n\n"
            f"🔢 **Request ID:** `{req_id}`\n"
            f"🎬 **Title:** `{movie_req.title}`\n\n"
            f"Our administrators have been notified. You will automatically receive a message here when the movie is indexed."
        )

    @client.on_callback_query(filters.regex(r"^req_ful\|"))
    async def handle_admin_fulfillment(bot: Client, query: CallbackQuery) -> None:
        user_id = query.from_user.id

        if ADMIN_USER_IDS and user_id not in ADMIN_USER_IDS:
            await query.answer("⛔ Unauthorized: Admin access required.", show_alert=True)
            return

        req_id = query.data.split("|")[1]
        req_doc = await repo.get_request_by_id(req_id)

        if not req_doc:
            await query.answer("❌ Request record not found.", show_alert=True)
            return

        if req_doc.get("status") == RequestStatus.FULFILLED.value:
            await query.answer("ℹ️ Request has already been fulfilled.", show_alert=True)
            return

        title = req_doc["title"]
        regex_query = {"$regex": title, "$options": "i"}
        mongo_query = {
            "$or": [
                {"normalized_title": regex_query},
                {"clean_name": regex_query},
                {"title": regex_query},
            ]
        }
        if req_doc.get("year"):
            mongo_query["year"] = req_doc["year"]

        matches = await db_manager.find_in_all_shards(mongo_query, limit=1)

        if not matches:
            await query.answer(
                "⚠️ Movie not found in database yet!\n\nPlease ensure the file has been uploaded and indexed.",
                show_alert=True,
            )
            return

        success = await repo.mark_fulfilled(req_id)
        if not success:
            await query.answer("ℹ️ Request already processed.", show_alert=True)
            return

        target_user_id = req_doc["user_id"]
        notify_text = (
            f"🎉 **YOUR MOVIE IS NOW AVAILABLE!**\n\n"
            f"🎬 **{title}** ({req_doc.get('year') or 'N/A'})\n\n"
            f"The movie you requested has been uploaded and indexed in our database."
        )
        notify_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 GET MOVIE", callback_data=f"srch_t|{target_user_id}|{matches[0].get('normalized_title')}|{req_doc.get('year') or 0}")]
        ])

        try:
            await bot.send_message(target_user_id, notify_text, reply_markup=notify_keyboard)
            await query.answer("✅ User notified successfully!", show_alert=True)
        except Exception:
            await query.answer("⚠️ Movie verified, but could not notify user.", show_alert=True)

        updated_bin_text = query.message.text.replace("🟡 STATUS: PENDING", "🟢 STATUS: FULFILLED\n✅ User notified")
        try:
            await query.message.edit_text(updated_bin_text, reply_markup=None)
        except Exception:
            pass
