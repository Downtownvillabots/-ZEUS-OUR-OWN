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
    if query.from_user.id not in ADMINS:
        await query.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴅᴏ ᴛʜɪꜱ.", show_alert=True)
        return

    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    user_id, search, chat_id = req
    remove_request(token)

    # Send to USER with premium format
    try:
        await client.send_message(
            user_id,
            script.REQUEST_AVAILABLE.format(query=search),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎬 ɢᴇᴛ ꜰɪʟᴇ 🎬", callback_data=f"getfile_{token}")
            ]])
        )
    except Exception:
        pass

    # Log to channel (fancy)
    await client.send_message(
        LOG_CHANNEL,
        f"✅ <b>ᴍᴀʀᴋᴇᴅ ᴀꜱ ᴀᴠᴀɪʟᴀʙʟᴇ</b>\n\n🔍 <code>{search}</code>\n👤 <code>{user_id}</code>",
        parse_mode="HTML"
    )

    await query.answer("✅ ᴅᴏɴᴇ!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^nrel_"))
async def mark_not_released(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴅᴏ ᴛʜɪꜱ.", show_alert=True)
        return

    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    user_id, search, chat_id = req
    remove_request(token)

    try:
        await client.send_message(
            user_id,
            script.REQUEST_NOT_RELEASED.format(query=search),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await client.send_message(
        LOG_CHANNEL,
        f"📌 <b>ɴᴏᴛ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ</b>\n\n🔍 <code>{search}</code>\n👤 <code>{user_id}</code>",
        parse_mode="HTML"
    )

    await query.answer("📌 ᴅᴏɴᴇ!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^unav_"))
async def mark_unavailable(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴅᴏ ᴛʜɪꜱ.", show_alert=True)
        return

    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    user_id, search, chat_id = req
    remove_request(token)

    try:
        await client.send_message(
            user_id,
            script.REQUEST_UNAVAILABLE.format(query=search),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await client.send_message(
        LOG_CHANNEL,
        f"❌ <b>ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ</b>\n\n🔍 <code>{search}</code>\n👤 <code>{user_id}</code>",
        parse_mode="HTML"
    )

    await query.answer("❌ ᴅᴏɴᴇ!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^cancel_"))
async def cancel_request(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴅᴏ ᴛʜɪꜱ.", show_alert=True)
        return

    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    remove_request(token)

    await query.answer("🗑️ ᴄᴀɴᴄᴇʟʟᴇᴅ!", show_alert=False)

@Client.on_callback_query(filters.regex(r"^getfile_"))
async def send_file_to_user(client, query):
    token = query.data.split("_", 1)[1]
    req = get_request(token)
    if not req:
        await query.answer("❌ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ.", show_alert=True)
        return

    user_id, search, chat_id = req
    files, offset, total = await get_search_results(user_id, search, max_results=1)
    if not files:
        await query.answer("❌ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ ʏᴇᴛ!", show_alert=True)
        return

    file = files[0]
    try:
        await client.send_cached_media(
            user_id,
            file.file_id,
            caption=f"🎬 <b>{file.file_name}</b>\n\n🔍 <i>{search}</i>",
            parse_mode="HTML"
        )
        await query.answer("✅ ꜰɪʟᴇ ꜱᴇɴᴛ!", show_alert=False)
        remove_request(token)
    except Exception:
        await query.answer("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ.", show_alert=True)
