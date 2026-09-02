import re
import uuid
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import get_search_results
from info import ADMINS, LOG_CHANNEL
from Script import script

# In-memory request store (no database)
# token -> (user_id, search_query, chat_id)
request_store = {}

def add_request(user_id, search, chat_id):
    token = uuid.uuid4().hex[:8]
    request_store[token] = (int(user_id), str(search), int(chat_id))
    return token

def get_request(token):
    return request_store.get(token)

def remove_request(token):
    request_store.pop(token, None)

@Client.on_callback_query(filters.regex(r"^avail_"))
async def mark_available(client, query):
    # Only admins can mark available
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Only admins can do this.", show_alert=True)
        return

    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ Request expired or already handled.", show_alert=True)
        return

    user_id, search, chat_id = req

    # Delete the request from memory
    remove_request(token)

    # Send fancy message to the user in PM
    try:
        await client.send_message(
            user_id,
            script.REQUEST_AVAILABLE.format(
                query=search,
                user_mention=query.from_user.mention if query.from_user else "User"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎬 GET FILES 🎬", callback_data=f"getfile_{token}")
            ]])
        )
    except Exception:
        pass

    # Optional: log to the channel
    await client.send_message(
        LOG_CHANNEL,
        f"✅ Request marked as available: {search}\nUser: {user_id}"
    )

    await query.answer("✅ Marked as available!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^getfile_"))
async def send_file_to_user(client, query):
    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ This file request has expired.", show_alert=True)
        return

    user_id, search, chat_id = req

    # Search for the file
    files, offset, total = await get_search_results(user_id, search, max_results=1)
    if not files:
        await query.answer("❌ File not found yet!", show_alert=True)
        return

    file = files[0]
    try:
        await client.send_cached_media(
            user_id,
            file.file_id,
            caption=f"🎬 {file.file_name}\n\n🔍 {search}"
        )
        await query.answer("✅ File sent!", show_alert=False)
        # Remove request after sending
        remove_request(token)
    except Exception:
        await query.answer("❌ Failed to send file.", show_alert=True)
