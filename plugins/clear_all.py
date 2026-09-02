import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, MULTIPLE_DB
from database.ia_filterdb import (
    DBS,          # list of media databases
    COLLECTIONS,  # list of media collections
    DB_LABELS,    # human-readable labels (Data-base-02, etc.)
    MODELS,       # umongo models (not used for delete)
)
from database.users_chats_db import db as user_db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# HELPER: GET MEDIA COLLECTION INDEXES
# ============================================================

def get_media_collections():
    """Return a list of (label, collection) for each media DB."""
    return list(zip(DB_LABELS, COLLECTIONS))

# ============================================================
# CLEAR MEDIA DATABASE
# ============================================================

async def clear_media_collection(collection, label):
    """Delete all documents from a media collection and log."""
    try:
        result = await collection.delete_many({})
        logger.info(f"[CLEAR] Deleted {result.deleted_count} files from {label}.")
        return result.deleted_count
    except Exception as e:
        logger.error(f"[CLEAR] Failed to clear {label}: {e}")
        return 0

async def clear_all_media():
    """Clear all media collections."""
    total = 0
    for label, collection in get_media_collections():
        count = await clear_media_collection(collection, label)
        total += count
    logger.info(f"[CLEAR] Cleared all media databases – total {total} files.")
    return total

# ============================================================
# CLEAR USER DATABASE
# ============================================================

async def clear_user_collection(col, name):
    """Delete all documents from a user collection and log."""
    try:
        result = await col.delete_many({})
        logger.info(f"[CLEAR] Deleted {result.deleted_count} documents from {name}.")
        return result.deleted_count
    except Exception as e:
        logger.error(f"[CLEAR] Failed to clear {name}: {e}")
        return 0

async def clear_user_db():
    """Clear all user-related collections (users, groups, premium, etc.)."""
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
    total = 0
    for name, col in collections.items():
        count = await clear_user_collection(col, name)
        total += count
    logger.info(f"[CLEAR] Cleared user database – total {total} documents.")
    return total

# ============================================================
# MENU
# ============================================================

def build_clear_menu():
    """Build inline keyboard for clear options."""
    buttons = []
    # All media
    buttons.append([InlineKeyboardButton("🗑️ Clear ALL Media DBs", callback_data="clear_media_all")])
    # User DB
    buttons.append([InlineKeyboardButton("🗑️ Clear USER DB", callback_data="clear_user_all")])
    # Individual media DBs
    for idx, label in enumerate(DB_LABELS):
        buttons.append([InlineKeyboardButton(f"🗑️ Clear {label}", callback_data=f"clear_single#{idx}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="clear_close")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# COMMAND: /clearall
# ============================================================

@Client.on_message(filters.command("clearall") & filters.user(ADMINS))
async def clearall_command(client, message):
    logger.info(f"[CLEAR] Admin {message.from_user.id} used /clearall.")
    text = "🗑️ **Database Cleanup Menu**\n\nChoose what to clear:"
    await message.reply_text(
        text,
        reply_markup=build_clear_menu(),
        parse_mode="MARKDOWN"
    )

# ============================================================
# CALLBACKS
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

# Confirmation callbacks
@Client.on_callback_query(filters.regex(r"^confirm_media_all$"))
async def confirm_media_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEAR] Admin {query.from_user.id} confirmed clearing ALL media DBs.")
    await query.message.edit_text("🧹 Clearing all media databases...")
    await query.answer("Clearing...", show_alert=False)
    total = await clear_all_media()
    await query.message.edit_text(f"✅ Cleared all media databases.\nTotal files removed: **{total}**")
    await query.answer("✅ Done!")

@Client.on_callback_query(filters.regex(r"^confirm_user_all$"))
async def confirm_user_all_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEAR] Admin {query.from_user.id} confirmed clearing USER DB.")
    await query.message.edit_text("🧹 Clearing user database...")
    await query.answer("Clearing...", show_alert=False)
    total = await clear_user_db()
    await query.message.edit_text(f"✅ Cleared user database.\nTotal documents removed: **{total}**")
    await query.answer("✅ Done!")

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
    count = await clear_media_collection(collection, label)
    await query.message.edit_text(f"✅ Cleared {label}.\nTotal files removed: **{count}**")
    await query.answer("✅ Done!")

@Client.on_callback_query(filters.regex(r"^clear_cancel$"))
async def clear_cancel_cb(client, query):
    await query.message.edit_text("❌ Operation cancelled.")
    await query.answer("Cancelled")

@Client.on_callback_query(filters.regex(r"^clear_close$"))
async def clear_close_cb(client, query):
    await query.message.delete()
    await query.answer("Closed")
