import logging
import asyncio
import html
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    Message, Photo, Document, Video, Audio
)
from pyrogram.errors import (
    FloodWait, ChatAdminRequired, PeerIdInvalid, Forbidden,
    MessageDeleteForbidden, RPCError, UserIsBlocked, InputUserDeactivated
)

from info import ADMINS, DELETE_TIME, LOG_CHANNEL
from database.users_chats_db import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# CONFIG / CONSTANTS
# ============================================================
COLLECTION_CHANNELS = "superbroadcast_channels"
COLLECTION_HISTORY = "superbroadcast_history"
MAX_CHANNELS_PAGE = 5
MAX_USERS_PER_BATCH = 100
DEFAULT_CAPTION = "🎬 <b>{title}</b>\n\n📁 {filename}\n💾 {filesize}\n🔗 {link}"

# ============================================================
# SESSION STATE (per admin)
# ============================================================
SUPER_STATE: Dict[int, Dict[str, Any]] = {}

# ============================================================
# ADMIN CHECK
# ============================================================
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ============================================================
# DB HELPERS
# ============================================================
async def get_channels_collection():
    return db[COLLECTION_CHANNELS]

async def get_history_collection():
    return db[COLLECTION_HISTORY]

# ============================================================
# CAPTION STORAGE
# ============================================================
async def get_global_caption() -> str:
    col = await get_channels_collection()
    doc = await col.find_one({"type": "global_caption"})
    return doc["caption"] if doc and doc.get("caption") else DEFAULT_CAPTION

async def set_global_caption(caption: str):
    col = await get_channels_collection()
    await col.update_one({"type": "global_caption"}, {"$set": {"caption": caption}}, upsert=True)

async def get_channel_caption(channel_id: int) -> Optional[str]:
    col = await get_channels_collection()
    doc = await col.find_one({"channel_id": channel_id})
    return doc.get("caption") if doc else None

async def set_channel_caption(channel_id: int, caption: str):
    col = await get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": {"caption": caption}})

async def reset_channel_caption(channel_id: int):
    col = await get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": {"caption": None}})

# ============================================================
# CHANNEL MANAGEMENT
# ============================================================
async def add_channel(channel_id: int) -> bool:
    col = await get_channels_collection()
    exists = await col.find_one({"channel_id": channel_id})
    if exists:
        return False
    await col.insert_one({
        "channel_id": channel_id,
        "enabled": True,
        "caption": None,
        "last_broadcast": None,
        "last_error": None,
        "title": "",
        "username": ""
    })
    return True

async def remove_channel(channel_id: int):
    col = await get_channels_collection()
    await col.delete_one({"channel_id": channel_id})

async def get_all_channels() -> List[dict]:
    col = await get_channels_collection()
    channels = []
    async for doc in col.find({"type": {"$ne": "global_caption"}}):
        channels.append(doc)
    return channels

async def update_channel(channel_id: int, **kwargs):
    col = await get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": kwargs})

# ============================================================
# CHANNEL VALIDATION
# ============================================================
async def validate_channel(client: Client, channel_id: int) -> Tuple[str, str]:
    try:
        chat = await client.get_chat(channel_id)
        title = chat.title or str(channel_id)
        member = await client.get_chat_member(channel_id, "me")
        if member.status == enums.ChatMemberStatus.ADMINISTRATOR:
            return "CONNECTED", title
        return "BOT_NOT_ADMIN", title
    except PeerIdInvalid:
        return "INVALID", ""
    except ChatAdminRequired:
        return "BOT_NOT_ADMIN", ""
    except Exception as e:
        logger.error(f"Channel validation error: {e}")
        return "ERROR", ""

# ============================================================
# CAPTION RENDERING & METADATA EXTRACTION
# ============================================================
def render_caption(template: str, data: dict) -> str:
    for key, value in data.items():
        template = template.replace("{" + key + "}", str(value))
    template = re.sub(r"{[^}]*}", "", template)
    return template

def extract_metadata_from_filename(filename: str) -> dict:
    """Extract quality, year, language, season, episode from filename."""
    meta = {
        "quality": "",
        "year": "",
        "language": "",
        "season": "",
        "episode": "",
        "part": ""
    }
    if not filename:
        return meta
    # Quality
    q_match = re.search(r'(\d{3,4}[pP]|4K|2160p|1080p|720p|480p|360p)', filename)
    if q_match:
        meta["quality"] = q_match.group(1)
    # Year
    y_match = re.search(r'(19\d{2}|20\d{2})', filename)
    if y_match:
        meta["year"] = y_match.group(1)
    # Language
    langs = ["Hindi", "Tamil", "Telugu", "Malayalam", "English", "Kannada", "Bengali", "Punjabi"]
    for lang in langs:
        if lang.lower() in filename.lower():
            meta["language"] = lang
            break
    # Season/Episode
    s_match = re.search(r'S(\d{1,2})', filename, re.IGNORECASE)
    if s_match:
        meta["season"] = "S" + s_match.group(1).zfill(2)
    e_match = re.search(r'E(\d{1,2})', filename, re.IGNORECASE)
    if e_match:
        meta["episode"] = "E" + e_match.group(1).zfill(2)
    # Part
    p_match = re.search(r'Part\s*(\d+)|part(\d+)', filename, re.IGNORECASE)
    if p_match:
        meta["part"] = "Part " + (p_match.group(1) or p_match.group(2))
    return meta

def extract_metadata_from_file_message(message: Message) -> dict:
    """Extract file size, filename, etc from the sent file."""
    if message.document:
        return {
            "filename": message.document.file_name or "Unknown",
            "filesize": human_size(message.document.file_size) if message.document.file_size else "0 B",
            "mime_type": message.document.mime_type or "",
        }
    elif message.video:
        return {
            "filename": "Video",
            "filesize": human_size(message.video.file_size) if message.video.file_size else "0 B",
            "mime_type": "video"
        }
    elif message.audio:
        return {
            "filename": "Audio",
            "filesize": human_size(message.audio.file_size) if message.audio.file_size else "0 B",
            "mime_type": "audio"
        }
    else:
        return {"filename": "Unknown", "filesize": "0 B", "mime_type": ""}

def human_size(size: int) -> str:
    """Convert bytes to human-readable string."""
    size = float(size)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

# ============================================================
# SESSION MANAGEMENT
# ============================================================
async def start_release_session(user_id: int):
    SUPER_STATE[user_id] = {
        "stage": "poster",
        "poster": None,
        "files": [],
        "title": "",
        "caption": None,
        "destinations": None,
        "last_message_id": None,
        "created_at": time.time(),
        "paused": False,
        "cancelled": False,
    }

async def clear_release_session(user_id: int):
    SUPER_STATE.pop(user_id, None)

# ============================================================
# MAIN COMMAND
# ============================================================
@Client.on_message(filters.command("superbroadcast") & filters.private)
async def superbroadcast_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("❌ **Admin Only** – You are not authorized.")
        return
    logger.info(f"SUPERBROADCAST: Admin {message.from_user.id} opened dashboard")
    await show_main_dashboard(client, message.chat.id, message.id)

# ============================================================
# MAIN DASHBOARD
# ============================================================
async def show_main_dashboard(client: Client, chat_id: int, message_id: int = None):
    channels = await get_all_channels()
    users_count = await db.users.count_documents({})

    text = (
        "╔══════════════════════════════════════════════════════╗\n"
        "║              🚀 SUPER BROADCAST CORE                ║\n"
        "║                 RELEASE DISTRIBUTION                 ║\n"
        "╚══════════════════════════════════════════════════════╝\n\n"
        "🟢 SYSTEM: ONLINE\n"
        "👤 ADMIN: AUTHORIZED\n"
        f"📡 CHANNELS: {len(channels)}\n"
        f"👥 USERS: {users_count:,}\n"
        "📝 CAPTION ENGINE: ACTIVE\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 DISTRIBUTION STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Connected Channels : {len(channels)}\n"
        "👥 PM Distribution     : ENABLED\n\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 NEW RELEASE", callback_data="sb_new_release")],
        [InlineKeyboardButton("📡 CHANNELS", callback_data="sb_channels"),
         InlineKeyboardButton("👥 USER PM", callback_data="sb_pm_settings")],
        [InlineKeyboardButton("📝 CAPTIONS", callback_data="sb_captions"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="sb_settings")],
        [InlineKeyboardButton("📊 HISTORY", callback_data="sb_history"),
         InlineKeyboardButton("📈 STATISTICS", callback_data="sb_stats")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sb_refresh"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sb_close")],
    ])

    if message_id:
        await client.edit_message_text(chat_id, message_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    else:
        await client.send_message(chat_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# ============================================================
# CHANNEL MANAGEMENT CALLBACKS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_main$"))
async def back_to_main(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await show_main_dashboard(client, query.message.chat.id, query.message.id)

@Client.on_callback_query(filters.regex(r"^sb_refresh$"))
async def refresh_main(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await show_main_dashboard(client, query.message.chat.id, query.message.id)

@Client.on_callback_query(filters.regex(r"^sb_close$"))
async def close_panel(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.delete()
    await query.answer("Closed")

@Client.on_callback_query(filters.regex(r"^sb_channels$"))
async def channels_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    text = "📡 **CHANNEL MANAGEMENT**\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            status = "🟢" if ch.get("enabled", True) else "🔴"
            title = ch.get("title") or ch["channel_id"]
            text += f"{status} {i}. {html.escape(title)}\n"
    else:
        text += "No channels configured.\n\nUse ➕ ADD to add channel IDs."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD", callback_data="sb_add_channel"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="sb_refresh_channels")],
        [InlineKeyboardButton("🗑️ REMOVE", callback_data="sb_remove_channel_menu"),
         InlineKeyboardButton("🧪 TEST", callback_data="sb_test_channels")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_add_channel$"))
async def add_channel_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "➕ **ADD CHANNEL**\n\nSend the channel ID(s) (comma separated):\n\n"
        "Example:\n-1001234567890,-1009876543210",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_channels")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "add_channel"}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS) & filters.regex(r"^-?\d"))
async def capture_channel_ids(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "add_channel":
        return
    ids = message.text.replace(" ", "").split(",")
    added, failed = 0, []
    for id_str in ids:
        try:
            cid = int(id_str)
        except ValueError:
            failed.append(id_str)
            continue
        if await add_channel(cid):
            added += 1
        else:
            failed.append(id_str)
    SUPER_STATE.pop(user_id, None)
    await message.reply_text(f"✅ Added {added} channels. Failed: {len(failed)} {failed}")
    await channels_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_remove_channel_menu$"))
async def remove_channel_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    if not channels:
        await query.answer("No channels configured", show_alert=True)
        return
    keyboard = []
    for ch in channels:
        title = ch.get("title") or ch["channel_id"]
        keyboard.append([InlineKeyboardButton(f"🗑️ {html.escape(title)}", callback_data=f"sb_rm_{ch['channel_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_channels")])
    await query.message.edit_text("🗑️ **Select channel to remove:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_rm_(\-?\d+)$"))
async def remove_channel_confirm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    await remove_channel(cid)
    logger.info(f"SUPERBROADCAST: Admin removed channel {cid}")
    await query.answer(f"Removed {cid}", show_alert=True)
    await channels_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_refresh_channels$"))
async def refresh_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    for ch in channels:
        status, title = await validate_channel(client, ch["channel_id"])
        await update_channel(ch["channel_id"], status=status, title=title)
    await query.answer("✅ Refreshed channel statuses")
    await channels_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_test_channels$"))
async def test_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    for ch in channels:
        status, _ = await validate_channel(client, ch["channel_id"])
        await update_channel(ch["channel_id"], status=status)
    await query.answer("✅ Tested all channels", show_alert=True)
    await channels_menu(client, query)

# ============================================================
# CAPTIONS MENU
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_captions$"))
async def captions_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = "📝 **CAPTION CENTER**\n\nChoose caption type:\n\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 GLOBAL DEFAULT", callback_data="sb_caption_global")],
        [InlineKeyboardButton("📡 PER-CHANNEL", callback_data="sb_caption_channel_menu")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_global$"))
async def global_caption_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    caption = await get_global_caption()
    text = (
        "🌐 **GLOBAL DEFAULT CAPTION**\n\n"
        "**Current:**\n"
        f"{html.escape(caption)}\n\n"
        "**Example Placeholders:**\n"
        "`{title}` - movie/series title\n"
        "`{filename}` - file name\n"
        "`{filesize}` - file size\n"
        "`{quality}` - quality (720p, 1080p, etc.)\n"
        "`{year}` - release year\n"
        "`{language}` - language\n"
        "`{season}` - season (e.g., S01)\n"
        "`{episode}` - episode (e.g., E03)\n"
        "`{part}` - part number\n"
        "`{channel}` - channel name\n"
        "`{date}` - current date\n"
        "`{time}` - current time\n"
        "`{link}` - stream/download link\n\n"
        "**HTML Example:**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "💾 Size: {filesize}\n"
        "📁 File: {filename}\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ VIEW", callback_data="sb_caption_global_view"),
         InlineKeyboardButton("✏️ EDIT", callback_data="sb_caption_global_edit")],
        [InlineKeyboardButton("🔄 RESET", callback_data="sb_caption_global_reset"),
         InlineKeyboardButton("🧪 TEST", callback_data="sb_caption_global_test")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_captions")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_edit$"))
async def global_caption_edit_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "✏️ **EDIT GLOBAL CAPTION**\n\n"
        "Send the new caption as a message.\n\n"
        "**Example HTML (copy/paste and modify):**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "💾 Size: {filesize}\n"
        "📁 File: {filename}\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```\n\n"
        "Now send your caption:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_caption_global")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "edit_global_caption"}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def capture_global_caption(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "edit_global_caption":
        return
    await set_global_caption(message.text.html)
    SUPER_STATE.pop(user_id, None)
    logger.info(f"SUPERBROADCAST: Global caption updated by {user_id}")
    await message.reply_text("✅ **Global caption updated.**")
    await global_caption_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_reset$"))
async def global_caption_reset(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await set_global_caption(DEFAULT_CAPTION)
    await query.answer("✅ Global caption reset to default", show_alert=True)
    await global_caption_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_test$"))
async def global_caption_test(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("🧪 Test sent", show_alert=True)
    test_data = {
        "title": "Example Movie 2026",
        "filename": "Example.Movie.1080p.mkv",
        "filesize": "1.2 GB",
        "quality": "1080p",
        "year": "2026",
        "language": "English",
        "season": "S01",
        "episode": "E03",
        "part": "Part 1",
        "channel": "Test Channel",
        "link": "https://t.me/example"
    }
    caption = await get_global_caption()
    text = render_caption(caption, test_data)
    await client.send_message(query.from_user.id, text, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_channel_menu$"))
async def caption_channel_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    keyboard = []
    for ch in channels:
        title = ch.get("title") or ch["channel_id"]
        keyboard.append([InlineKeyboardButton(f"📡 {html.escape(title)}", callback_data=f"sb_chcap_{ch['channel_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_captions")])
    await query.message.edit_text("📡 **Select channel for caption edit:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_chcap_(\-?\d+)$"))
async def channel_caption_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    ch = await get_channels_collection().find_one({"channel_id": cid})
    if not ch:
        await query.answer("Channel not found", show_alert=True)
        return
    current = ch.get("caption") or (await get_global_caption())
    text = (
        "📝 **CHANNEL CAPTION**\n\n"
        f"📡 Channel: {html.escape(ch.get('title', cid))}\n"
        f"🟢 Status: {ch.get('status', 'UNKNOWN')}\n\n"
        "**Current Caption:**\n"
        f"{html.escape(current)}\n\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ VIEW", callback_data=f"sb_chcap_view_{cid}"),
         InlineKeyboardButton("✏️ EDIT", callback_data=f"sb_chcap_edit_{cid}")],
        [InlineKeyboardButton("🔄 RESET TO DEFAULT", callback_data=f"sb_chcap_reset_{cid}"),
         InlineKeyboardButton("🧪 TEST", callback_data=f"sb_chcap_test_{cid}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_caption_channel_menu")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_chcap_edit_(\-?\d+)$"))
async def channel_caption_edit_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[3])
    await query.message.edit_text(
        "✏️ **EDIT CHANNEL CAPTION**\n\n"
        "Send the new caption for this channel.\n\n"
        "**Example HTML:**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "💾 Size: {filesize}\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```\n\n"
        "Now send your caption:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data=f"sb_chcap_{cid}")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "edit_channel_caption", "channel_id": cid}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def capture_channel_caption(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "edit_channel_caption":
        return
    cid = state["channel_id"]
    await set_channel_caption(cid, message.text.html)
    SUPER_STATE.pop(user_id, None)
    logger.info(f"SUPERBROADCAST: Channel caption updated for {cid} by {user_id}")
    await message.reply_text("✅ **Channel caption updated.**")
    await caption_channel_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_chcap_reset_(\-?\d+)$"))
async def channel_caption_reset(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[3])
    await reset_channel_caption(cid)
    await query.answer("✅ Channel caption reset to default", show_alert=True)
    await channel_caption_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_chcap_test_(\-?\d+)$"))
async def channel_caption_test(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[3])
    ch = await get_channels_collection().find_one({"channel_id": cid})
    caption = ch.get("caption") or (await get_global_caption())
    test_data = {
        "title": "Example Movie 2026",
        "filename": "Example.Movie.1080p.mkv",
        "filesize": "1.2 GB",
        "quality": "1080p",
        "year": "2026",
        "language": "English",
        "season": "S01",
        "episode": "E03",
        "part": "Part 1",
        "channel": ch.get("title", cid),
        "link": "https://t.me/example"
    }
    text = render_caption(caption, test_data)
    await client.send_message(query.from_user.id, text, parse_mode=enums.ParseMode.HTML)

# ============================================================
# PM SETTINGS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_pm_settings$"))
async def pm_settings(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = await get_channels_collection()
    doc = await col.find_one({"type": "pm_settings"})
    enabled = doc.get("enabled", True) if doc else True
    text = f"👥 **PM DISTRIBUTION**\n\nEnabled: {'✅' if enabled else '❌'}\n\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ENABLE", callback_data="sb_pm_enable"),
         InlineKeyboardButton("❌ DISABLE", callback_data="sb_pm_disable")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_pm_enable$"))
async def pm_enable(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = await get_channels_collection()
    await col.update_one({"type": "pm_settings"}, {"$set": {"enabled": True}}, upsert=True)
    await query.answer("✅ PM distribution enabled", show_alert=True)
    await pm_settings(client, query)

@Client.on_callback_query(filters.regex(r"^sb_pm_disable$"))
async def pm_disable(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = await get_channels_collection()
    await col.update_one({"type": "pm_settings"}, {"$set": {"enabled": False}}, upsert=True)
    await query.answer("❌ PM distribution disabled", show_alert=True)
    await pm_settings(client, query)

# ============================================================
# NEW RELEASE WIZARD
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_new_release$"))
async def new_release_start(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await start_release_session(query.from_user.id)
    await query.message.edit_text(
        "🎬 **NEW RELEASE**\n\nSend a **poster** (photo) to begin.\n\n"
        "Or send /cancel to abort.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data="sb_cancel_release")]]),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex(r"^sb_cancel_release$"))
async def cancel_release(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await clear_release_session(query.from_user.id)
    await query.message.edit_text("❌ **Release cancelled.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]]))
    await query.answer("Cancelled")

@Client.on_message(filters.private & filters.user(ADMINS) & (filters.photo | filters.document | filters.video | filters.audio))
async def release_media_collect(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") not in ("poster", "files"):
        return

    if state["stage"] == "poster":
        if message.photo:
            state["poster"] = message.photo.file_id
            state["stage"] = "files"
            await message.reply_text(
                "📦 **Now send files** (multiple allowed).\n\n"
                "When done, click ✅ FINISH FILES.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ FINISH FILES", callback_data="sb_finish_files")]])
            )
        else:
            await message.reply_text("Please send a photo as poster, or /cancel.")
        return

    if state["stage"] == "files":
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name or "Document"
        elif message.video:
            file_id = message.video.file_id
            file_name = "Video"
        elif message.audio:
            file_id = message.audio.file_id
            file_name = "Audio"
        else:
            await message.reply_text("❌ Unsupported file type.")
            return
        # Extract metadata from file name and message
        meta = extract_metadata_from_filename(file_name)
        meta.update(extract_metadata_from_file_message(message))
        state["files"].append({
            "file_id": file_id,
            "file_name": file_name,
            "metadata": meta
        })
        logger.info(f"SUPERBROADCAST: Admin {user_id} added file {file_name}")
        await message.reply_text(
            f"✅ Added file: <code>{html.escape(file_name)}</code> (Total: {len(state['files'])})",
            parse_mode=enums.ParseMode.HTML
        )

# ============================================================
# DESTINATION SELECTION
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_finish_files$"))
async def finish_files(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "files":
        await query.answer("No active release session", show_alert=True)
        return
    if not state["files"]:
        await query.answer("⚠️ No files collected yet", show_alert=True)
        return
    await query.message.edit_text(
        "🎬 **Release Title**\n\nSend the title/name of the release (e.g., Movie 2026).\n\n"
        "Or click ⏭️ SKIP to use default.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ SKIP", callback_data="sb_title_skip")]]),
        parse_mode=enums.ParseMode.HTML
    )
    state["stage"] = "title"

@Client.on_callback_query(filters.regex(r"^sb_title_skip$"))
async def title_skip(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "title":
        return
    state["title"] = "Release"
    state["stage"] = "destination"
    await show_destination_menu(client, query)

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def capture_release_title(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "title":
        return
    state["title"] = message.text.strip()
    state["stage"] = "destination"
    logger.info(f"SUPERBROADCAST: Release title set to {state['title']} by {user_id}")
    await message.reply_text("✅ Title set. Now choose destination.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 SELECT DESTINATION", callback_data="sb_dest_menu")]]))

@Client.on_callback_query(filters.regex(r"^sb_dest_menu$"))
async def show_destination_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "destination":
        return
    text = (
        "🎯 **SELECT DESTINATION**\n\n"
        "Choose where this release should go:\n\n"
        "• 📡 SELECT CHANNELS (specific)\n"
        "• 📡 ALL CHANNELS (all enabled)\n"
        "• 👥 ALL USERS (PM)\n"
        "• 🌐 CHANNELS + USERS\n\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 SELECT CHANNELS", callback_data="sb_dest_select")],
        [InlineKeyboardButton("📡 ALL CHANNELS", callback_data="sb_dest_all")],
        [InlineKeyboardButton("👥 ALL USERS / PM", callback_data="sb_dest_pm")],
        [InlineKeyboardButton("🌐 CHANNELS + USERS", callback_data="sb_dest_both")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="sb_cancel_release")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_dest_select$"))
async def dest_select_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    enabled_channels = [ch for ch in channels if ch.get("enabled", True)]
    if not enabled_channels:
        await query.answer("No enabled channels found", show_alert=True)
        return
    state["selected_channels"] = []
    state["stage"] = "dest_select"
    await show_channel_selection(client, query, 0)

async def show_channel_selection(client: Client, query: CallbackQuery, page: int):
    state = SUPER_STATE.get(query.from_user.id)
    channels = await get_all_channels()
    enabled_channels = [ch for ch in channels if ch.get("enabled", True)]
    per_page = MAX_CHANNELS_PAGE
    start = page * per_page
    end = start + per_page
    page_channels = enabled_channels[start:end]
    keyboard = []
    for ch in page_channels:
        title = ch.get("title") or ch["channel_id"]
        selected = "☑️" if ch["channel_id"] in state.get("selected_channels", []) else "☐"
        keyboard.append([InlineKeyboardButton(f"{selected} {html.escape(title)}", callback_data=f"sb_toggle_{ch['channel_id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"sb_dest_page_{page-1}"))
    if end < len(enabled_channels):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"sb_dest_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("✅ CONFIRM", callback_data="sb_dest_confirm")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_dest_menu")])
    await query.message.edit_text("📡 **Select channels**\n\nClick to toggle selection:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_dest_page_(\d+)$"))
async def dest_page(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    page = int(query.data.split("_")[3])
    await show_channel_selection(client, query, page)

@Client.on_callback_query(filters.regex(r"^sb_toggle_(\-?\d+)$"))
async def toggle_channel(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    if cid in state.get("selected_channels", []):
        state["selected_channels"].remove(cid)
    else:
        state["selected_channels"].append(cid)
    # refresh page (use page 0 for simplicity, but better to track current page)
    await show_channel_selection(client, query, 0)

@Client.on_callback_query(filters.regex(r"^sb_dest_all$"))
async def dest_all(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    state["selected_channels"] = [ch["channel_id"] for ch in channels if ch.get("enabled", True)]
    state["stage"] = "dest_confirm"
    await query.message.edit_text(
        f"📡 **You selected ALL channels ({len(state['selected_channels'])})**\n\n"
        "Ready to start?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 START BROADCAST", callback_data="sb_start_broadcast")],
            [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^sb_dest_pm$"))
async def dest_pm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    state["selected_channels"] = []
    state["pm_distribution"] = True
    state["stage"] = "dest_confirm"
    await query.message.edit_text(
        "👥 **PM DISTRIBUTION**\n\n"
        "Broadcast to all users?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 START BROADCAST", callback_data="sb_start_broadcast")],
            [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^sb_dest_both$"))
async def dest_both(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    state["selected_channels"] = [ch["channel_id"] for ch in channels if ch.get("enabled", True)]
    state["pm_distribution"] = True
    state["stage"] = "dest_confirm"
    await query.message.edit_text(
        "🌐 **CHANNELS + USERS**\n\n"
        f"Broadcast to {len(state['selected_channels'])} channels and all users?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 START BROADCAST", callback_data="sb_start_broadcast")],
            [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^sb_dest_confirm$"))
async def dest_confirm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    selected = state.get("selected_channels", [])
    pm = state.get("pm_distribution", False)
    if not selected and not pm:
        await query.answer("No destination selected", show_alert=True)
        return
    await query.message.edit_text(
        f"📡 **DESTINATIONS**\n\n"
        f"Channels: {len(selected)}\n"
        f"PM: {'Yes' if pm else 'No'}\n\n"
        "Ready?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 START BROADCAST", callback_data="sb_start_broadcast")],
            [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
        ])
    )

# ============================================================
# BROADCAST EXECUTION
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_start_broadcast$"))
async def start_broadcast(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        await query.answer("Session expired", show_alert=True)
        return
    # Build release data
    release = {
        "title": state.get("title", "Release"),
        "poster": state.get("poster"),
        "files": state.get("files", []),
        "caption": state.get("caption"),
        "channels": state.get("selected_channels", []),
        "pm": state.get("pm_distribution", False)
    }
    # Start broadcast task
    logger.info(f"SUPERBROADCAST: Admin {query.from_user.id} started broadcast for {release['title']}")
    asyncio.create_task(execute_broadcast(client, query.from_user.id, release))
    await query.message.edit_text(
        "🚀 **BROADCAST STARTED**\n\n"
        "Live monitor will update shortly.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 LOGS", callback_data="sb_live_logs")]])
    )

async def execute_broadcast(client: Client, admin_id: int, release: dict):
    """Background task for broadcast."""
    try:
        logger.info(f"SUPERBROADCAST: Starting broadcast for {release['title']} by admin {admin_id}")
        total_channels = len(release["channels"])
        total_users = await db.users.count_documents({}) if release["pm"] else 0
        completed_channels = 0
        failed_channels = 0
        sent_users = 0
        failed_users = 0
        start_time = time.time()

        # Send to channels
        for ch_id in release["channels"]:
            try:
                await send_release_to_channel(client, ch_id, release)
                completed_channels += 1
                logger.info(f"SUPERBROADCAST: Sent to channel {ch_id}")
            except FloodWait as e:
                logger.warning(f"SUPERBROADCAST: FloodWait on channel {ch_id}: {e.value}s")
                await asyncio.sleep(e.value)
                try:
                    await send_release_to_channel(client, ch_id, release)
                    completed_channels += 1
                except Exception as e2:
                    failed_channels += 1
                    logger.error(f"SUPERBROADCAST: Failed channel {ch_id} after flood: {e2}")
            except Exception as e:
                failed_channels += 1
                logger.error(f"SUPERBROADCAST: Failed channel {ch_id}: {e}")

        # Send to users
        if release["pm"]:
            users_cursor = db.users.find({})
            async for user in users_cursor:
                user_id = user.get("user_id")
                if not user_id:
                    continue
                try:
                    await send_release_to_user(client, user_id, release)
                    sent_users += 1
                except FloodWait as e:
                    logger.warning(f"SUPERBROADCAST: FloodWait for user {user_id}: {e.value}s")
                    await asyncio.sleep(e.value)
                    try:
                        await send_release_to_user(client, user_id, release)
                        sent_users += 1
                    except Exception:
                        failed_users += 1
                except (UserIsBlocked, InputUserDeactivated):
                    failed_users += 1  # user inactive
                except Exception:
                    failed_users += 1

        elapsed = time.time() - start_time
        # Save history
        col = await get_history_collection()
        await col.insert_one({
            "title": release["title"],
            "admin_id": admin_id,
            "timestamp": datetime.utcnow(),
            "channels_total": total_channels,
            "channels_success": completed_channels,
            "channels_failed": failed_channels,
            "users_total": total_users,
            "users_sent": sent_users,
            "users_failed": failed_users,
            "duration": elapsed,
            "status": "COMPLETED" if failed_channels == 0 and failed_users == 0 else "PARTIAL"
        })
        logger.info(f"SUPERBROADCAST: Broadcast completed in {elapsed}s. Channels: {completed_channels}/{total_channels}, Users: {sent_users}/{total_users}")
        # Notify admin
        await client.send_message(admin_id, "✅ **Broadcast completed**\nSee history for details.")
    except Exception as e:
        logger.exception(f"SUPERBROADCAST: Broadcast crashed: {e}")

async def send_release_to_channel(client: Client, channel_id: int, release: dict):
    """Send a release to a single channel."""
    caption_template = release.get("caption") or (await get_channel_caption(channel_id)) or (await get_global_caption())
    data = {
        "title": release["title"],
        "channel": "channel",
        "date": datetime.now().strftime("%d %b %Y"),
        "time": datetime.now().strftime("%H:%M"),
        "link": ""
    }
    # Use first file to fill metadata
    if release["files"]:
        first_file = release["files"][0]
        data.update(first_file["metadata"])
        data["filename"] = first_file["file_name"]
        data["filesize"] = first_file["metadata"].get("filesize", "0 B")
        data["quality"] = first_file["metadata"].get("quality", "")
        data["year"] = first_file["metadata"].get("year", "")
    caption = render_caption(caption_template, data)
    if release["poster"]:
        await client.send_photo(channel_id, release["poster"], caption=caption, parse_mode=enums.ParseMode.HTML)
    else:
        await client.send_message(channel_id, caption, parse_mode=enums.ParseMode.HTML)
    # Send files with buttons
    if release["files"]:
        # Send first file as media, then others as separate messages or button
        # For simplicity, send each file with a button
        for file in release["files"]:
            await client.send_cached_media(
                channel_id,
                file["file_id"],
                caption=caption,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎬 GET FILES", callback_data="sb_get_files")]
                ])
            )

async def send_release_to_user(client: Client, user_id: int, release: dict):
    """Send a release to a single user via PM."""
    caption_template = release.get("caption") or (await get_global_caption())
    data = {
        "title": release["title"],
        "channel": "PM",
        "date": datetime.now().strftime("%d %b %Y"),
        "time": datetime.now().strftime("%H:%M"),
        "link": ""
    }
    if release["files"]:
        first_file = release["files"][0]
        data.update(first_file["metadata"])
        data["filename"] = first_file["file_name"]
        data["filesize"] = first_file["metadata"].get("filesize", "0 B")
    caption = render_caption(caption_template, data)
    if release["poster"]:
        await client.send_photo(user_id, release["poster"], caption=caption, parse_mode=enums.ParseMode.HTML)
    else:
        await client.send_message(user_id, caption, parse_mode=enums.ParseMode.HTML)
    for file in release["files"]:
        sent = await client.send_cached_media(user_id, file["file_id"])
        # Schedule auto-delete
        asyncio.create_task(auto_delete_message(client, user_id, sent.id))

# ============================================================
# AUTO-DELETE
# ============================================================
async def auto_delete_message(client: Client, chat_id: int, message_id: int):
    """Delete a message after DELETE_TIME seconds."""
    try:
        await asyncio.sleep(DELETE_TIME)
        await client.delete_messages(chat_id, message_id)
        logger.info(f"SUPERBROADCAST: Auto-deleted message {message_id} in {chat_id}")
    except MessageDeleteForbidden:
        logger.warning(f"SUPERBROADCAST: Cannot delete message {message_id} (no permission)")
    except Exception as e:
        logger.error(f"SUPERBROADCAST: Auto-delete error: {e}")

# ============================================================
# HISTORY & STATISTICS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_history$"))
async def show_history(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = await get_history_collection()
    history = []
    async for doc in col.find().sort("timestamp", -1).limit(10):
        history.append(doc)
    text = "📊 **BROADCAST HISTORY**\n\n"
    if history:
        for h in history:
            status = "🟢" if h["status"] == "COMPLETED" else "🟡"
            text += f"{status} {h['title']} - {h['timestamp'].strftime('%d %b %Y %H:%M')}\n"
            text += f"   Ch: {h['channels_success']}/{h['channels_total']} | Users: {h['users_sent']}/{h['users_total']}\n"
    else:
        text += "No broadcasts yet."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_stats$"))
async def show_stats(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = await get_history_collection()
    total_broadcasts = await col.count_documents({})
    total_channels = 0
    total_users = 0
    async for doc in col.find({}):
        total_channels += doc.get("channels_success", 0)
        total_users += doc.get("users_sent", 0)
    text = f"📈 **STATISTICS**\n\n"
    text += f"Total Broadcasts: {total_broadcasts}\n"
    text += f"Total Channel Deliveries: {total_channels}\n"
    text += f"Total PM Deliveries: {total_users}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# ============================================================
# SETTINGS MENU (minimal placeholder)
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_settings$"))
async def settings_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = "⚙️ **SETTINGS**\n\nComing soon."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# ============================================================
# LIVE LOGS (placeholder – already in admin panel)
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_live_logs$"))
async def show_live_logs(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.answer("Check admin panel -> LOGS")
    await query.message.reply_text("📜 Open /admin -> 📋 LOGS for live logs.")

# ============================================================
# END OF FILE
# ============================================================
