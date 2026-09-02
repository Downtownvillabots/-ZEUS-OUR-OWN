import logging
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, MULTIPLE_DB
from database.ia_filterdb import DBS, COLLECTIONS, DB_LABELS
from database.users_chats_db import db as user_db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# HELPERS: PROGRESS BAR
# ============================================================

def progress_bar(current, total, length=20):
    if total <= 0:
        return "0%" + " " * length
    percent = int(current / total * 100)
    filled = int(length * percent / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} {percent}%"

# ============================================================
# HELPERS: DELETE IN BATCHES (WITH PROGRESS)
# ============================================================

async def clear_media_collection(client, query, collection, label):
    """Delete all documents from a media collection in batches, showing progress."""
    try:
        total = await collection.count_documents({})
        if total == 0:
            logger.info(f"[CLEAR] {label} is already empty.")
            await query.message.edit_text(f"✅ {label} is already empty.")
            return 0

        deleted = 0
        batch_size = 1000
        await query.message.edit_text(
            f"🧹 Clearing {label}...\n\n"
            f"<code>{progress_bar(0, total)}</code>\n"
            f"Deleted: 0 / {total}"
        )

        while True:
            # Fetch a batch of _ids
            cursor = collection.find({}, {"_id": 1}).batch_size(batch_size).limit(batch_size)
            ids = []
            async for doc in cursor:
                ids.append(doc["_id"])
            if not ids:
                break
            result = await collection.delete_many({"_id": {"$in": ids}})
            deleted += result.deleted_count
            percent = progress_bar(deleted, total)
            await query.message.edit_text(
                f"🧹 Clearing {label}...\n\n"
                f"<code>{percent}</code>\n"
                f"Deleted: {deleted} / {total}"
            )
            await asyncio.sleep(0.5)  # small delay to avoid Telegram flood

        logger.info(f"[CLEAR] Deleted {deleted} files from {label}.")
        await query.message.edit_text(f"✅ Cleared {label}.\nTotal files removed: **{deleted}**")
        return deleted
    except Exception as e:
        logger.error(f"[CLEAR] Failed to clear {label}: {e}")
        await query.message.edit_text(f"❌ Failed to clear {label}: {e}")
        return 0

async def clear_user_collection(client, query, col, name):
    """Delete all documents from a user collection in batches, showing progress."""
    try:
        total = await col.count_documents({})
        if total == 0:
            logger.info(f"[CLEAR] {name} is already empty.")
            return 0

        deleted = 0
        batch_size = 1000
        await query.message.edit_text(
            f"🧹 Clearing {name}...\n\n"
            f"<code>{progress_bar(0, total)}</code>\n"
            f"Deleted: 0 / {total}"
        )

        while True:
            cursor = col.find({}, {"_id": 1}).batch_size(batch_size).limit(batch_size)
            ids = []
            async for doc in cursor:
                ids.append(doc["_id"])
            if not ids:
                break
            result = await col.delete_many({"_id": {"$in": ids}})
            deleted += result.deleted_count
            percent = progress_bar(deleted, total)
            await query.message.edit_text(
                f"🧹 Clearing {name}...\n\n"
                f"<code>{percent}</code>\n"
                f"Deleted: {deleted} / {total}"
            )
            await asyncio.sleep(0.5)

        logger.info(f"[CLEAR] Deleted {deleted} documents from {name}.")
        return deleted
    except Exception as e:
        logger.error(f"[CLEAR] Failed to clear {name}: {e}")
        return 0

async def clear_all_media(client, query):
    """Clear all media collections with progress."""
    total_files = 0
    for idx, (label, collection) in enumerate(zip(DB_LABELS, COLLECTIONS)):
        logger.info(f"[CLEAR] Starting clearing {label}.")
        count = await clear_media_collection(client, query, collection, label)
        total_files += count
    logger.info(f"[CLEAR] Cleared all media databases – total {total_files} files.")
    await query.message.edit_text(f"✅ All media databases cleared.\nTotal files removed: **{total_files}**")
    return total_files

async def clear_user_db(client, query):
    """Clear all user-related collections with progress."""
    collections = {
        "users": user_db.col,
        "groups": user_db.grp,
        "premium": user_db.users,
        "requests": user_db.req,
        "bot_settings": user_db.botcol,
        "misc": user_db.misc,
        "verify_id": user_db.verify_id,
        "codes": user_db.codes,
        "filename": user_db.filename_col,
        "movie_updates": user_db.movie_updates,
        "connections": user_db.connection,
    }
    total_docs = 0
    for name, col in collections.items():
        logger.info(f"[CLEAR] Starting clearing {name}.")
        count = await clear_user_collection(client, query, col, name)
        total_docs += count
    logger.info(f"[CLEAR] Cleared user database – total {total_docs} documents.")
    await query.message.edit_text(f"✅ User database cleared.\nTotal documents removed: **{total_docs}**")
    return total_docs

# ============================================================
# MENU
# ============================================================

def build_clear_menu():
    buttons = []
    buttons.append([InlineKeyboardButton("🗑️ Clear ALL Media DBs", callback_data="clear_media_all")])
    buttons.append([InlineKeyboardButton("🗑️ Clear USER DB", callback_data="clear_user_all")])
    for idx, label in enumerate(DB_LABELS):
        buttons.append([InlineKeyboardButton(f"🗑️ Clear {label}", callback_data=f"clear_single#{idx}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="clear_close")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# COMMAND: /clearall
# ============================================================

@Client.on_message(filters.command("clearall"))
async def clearall_command(client, message):
    logger.info(f"DEBUG: clearall command received from {message.from_user.id}")
    if message.from_user.id not in ADMINS:
        await message.reply_text("❌ Admins only.")
        return
    logger.info(f"[CLEAR] Admin {message.from_user.id} used /clearall.")
    text = "🗑️ **Database Cleanup Menu**\n\nChoose what to clear:"
    await message.reply_text(
        text,
        reply_markup=build_clear_menu(),
        parse_mode="MARKDOWN"
    )

# ============================================================
# CALLBACKS (initiate)
# ============================================================

@Client.on_callback_query(filters.regex(r"^clear_media_all$"))
async def clear_media_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "⚠️ **Are you sure?** This will delete ALL files from ALL media databases.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Delete All", callback_data="confirm_media_all")],
            [InlineKeyboardButton("❌ Cancel", callback_data="clear_cancel")]
        ]),
        parse_mode="MARKDOWN"
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^clear_user_all$"))
async def clear_user_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "⚠️ **Are you sure?** This will delete ALL user data (users, groups, premium, etc.).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Delete All", callback_data="confirm_user_all")],
            [InlineKeyboardButton("❌ Cancel", callback_data="clear_cancel")]
        ]),
        parse_mode="MARKDOWN"
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^clear_single#(\d+)$"))
async def clear_single_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    index = int(query.data.split("#")[1])
    if index >= len(DB_LABELS):
        await query.answer("❌ Invalid DB", show_alert=True)
        return
    label = DB_LABELS[index]
    await query.message.edit_text(
        f"⚠️ **Are you sure?** This will delete ALL files from {label}.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_single#{index}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="clear_cancel")]
        ]),
        parse_mode="MARKDOWN"
    )
    await query.answer()

# ============================================================
# CALLBACKS (confirm & execute)
# ============================================================

@Client.on_callback_query(filters.regex(r"^confirm_media_all$"))
async def confirm_media_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEAR] Admin {query.from_user.id} confirmed clearing ALL media DBs.")
    await query.message.edit_text("🧹 Clearing all media databases...")
    await query.answer("Clearing...", show_alert=False)
    await clear_all_media(client, query)

@Client.on_callback_query(filters.regex(r"^confirm_user_all$"))
async def confirm_user_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEAR] Admin {query.from_user.id} confirmed clearing USER DB.")
    await query.message.edit_text("🧹 Clearing user database...")
    await query.answer("Clearing...", show_alert=False)
    await clear_user_db(client, query)

@Client.on_callback_query(filters.regex(r"^confirm_single#(\d+)$"))
async def confirm_single_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    index = int(query.data.split("#")[1])
    if index >= len(DB_LABELS):
        await query.answer("❌ Invalid DB", show_alert=True)
        return
    label = DB_LABELS[index]
    collection = COLLECTIONS[index]
    logger.info(f"[CLEAR] Admin {query.from_user.id} confirmed clearing {label}.")
    await query.message.edit_text(f"🧹 Clearing {label}...")
    await query.answer("Clearing...", show_alert=False)
    await clear_media_collection(client, query, collection, label)

@Client.on_callback_query(filters.regex(r"^clear_cancel$"))
async def clear_cancel_cb(client, query):
    await query.message.edit_text("❌ Operation cancelled.")
    await query.answer("Cancelled")

@Client.on_callback_query(filters.regex(r"^clear_close$"))
async def clear_close_cb(client, query):
    await query.message.delete()
    await query.answer("Closed")
