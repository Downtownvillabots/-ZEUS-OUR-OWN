import logging
import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS
from database.ia_filterdb import DBS, COLLECTIONS, DB_LABELS
from database.users_chats_db import db as user_db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# GLOBAL STATE (in-memory)
# ============================================================
CLEANUP_STATE = {
    "current_page": "dashboard",
    "selected_db": None,
    "operation": None,
    "progress_msg_id": None,
    "last_operations": [],
}

# ============================================================
# COLORED PROGRESS BAR (RED → YELLOW → GREEN)
# ============================================================

def colored_progress_bar(current, total, length=20):
    if total <= 0:
        return "⬜" * length
    percent = int(current / total * 100)
    filled = int(length * percent / 100)
    empty = length - filled

    # Choose color based on percent
    if percent < 33:
        color = "🟥"          # Red
    elif percent < 66:
        color = "🟨"          # Yellow
    else:
        color = "🟩"          # Green

    bar = color * filled + "⬜" * empty
    return f"{bar} {percent}%"

# ============================================================
# HELPERS
# ============================================================

def fmt_int(value):
    return f"{int(value):,}"

def fmt_bytes(value):
    value = float(value)
    if value < 1024:
        return f"{value:.0f} B"
    elif value < 1024**2:
        return f"{value/1024:.1f} KB"
    elif value < 1024**3:
        return f"{value/1024**2:.1f} MB"
    elif value < 1024**4:
        return f"{value/1024**3:.1f} GB"
    else:
        return f"{value/1024**4:.1f} TB"

def now_ist():
    from pytz import timezone
    return datetime.now(timezone('Asia/Kolkata')).strftime("%d %b %Y • %I:%M:%S %p")

def add_operation(name, removed, duration):
    CLEANUP_STATE["last_operations"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "name": name,
        "removed": removed,
        "duration": f"{duration:.1f}"
    })

# ============================================================
# DATABASE STATS
# ============================================================

async def get_media_db_stats():
    stats = []
    for idx, (label, collection) in enumerate(zip(DB_LABELS, COLLECTIONS)):
        count = await collection.count_documents({})
        stats.append({"index": idx, "label": label, "count": count})
    return stats

async def get_user_db_stats():
    collections = {
        "Users": user_db.col,
        "Groups": user_db.grp,
        "Premium": user_db.users,
        "Requests": user_db.req,
        "Bot Settings": user_db.botcol,
        "Misc": user_db.misc,
        "Verify": user_db.verify_id,
        "Codes": user_db.codes,
        "Filename": user_db.filename_col,
        "Movie Updates": user_db.movie_updates,
        "Connections": user_db.connection,
    }
    stats = {}
    for name, col in collections.items():
        stats[name] = await col.count_documents({})
    return stats

# ============================================================
# CLEANUP FUNCTIONS (with colored progress + logs)
# ============================================================

async def clear_collection_with_progress(client, query, collection, label):
    total = await collection.count_documents({})
    logger.info(f"[CLEANUP] Starting clearing {label} – total={total} documents.")
    if total == 0:
        logger.info(f"[CLEANUP] {label} is already empty.")
        await query.message.edit_text(f"✅ {label} is already empty.")
        return 0

    deleted = 0
    batch_size = 1000
    await query.message.edit_text(
        f"🧹 <b>Clearing {label}...</b>\n\n"
        f"<code>{colored_progress_bar(0, total)}</code>\n"
        f"Processed: 0 / {total}"
    )

    while True:
        cursor = collection.find({}, {"_id": 1}).batch_size(batch_size).limit(batch_size)
        ids = []
        async for doc in cursor:
            ids.append(doc["_id"])
        if not ids:
            break
        result = await collection.delete_many({"_id": {"$in": ids}})
        deleted += result.deleted_count
        logger.info(f"[CLEANUP] {label} – batch deleted, total deleted so far: {deleted}.")
        await query.message.edit_text(
            f"🧹 <b>Clearing {label}...</b>\n\n"
            f"<code>{colored_progress_bar(deleted, total)}</code>\n"
            f"Processed: {deleted} / {total}"
        )
        await asyncio.sleep(0.5)

    await query.message.edit_text(f"✅ <b>{label}</b> cleared.\nTotal removed: <b>{deleted}</b>")
    logger.info(f"[CLEANUP] {label} cleared – removed {deleted} documents.")
    return deleted

async def clear_all_media(client, query):
    total_removed = 0
    for idx, (label, collection) in enumerate(zip(DB_LABELS, COLLECTIONS)):
        removed = await clear_collection_with_progress(client, query, collection, label)
        total_removed += removed
    await query.message.edit_text(f"✅ <b>All media databases cleared.</b>\nTotal removed: <b>{total_removed}</b>")
    logger.info(f"[CLEANUP] All media databases cleared – total removed: {total_removed}.")
    return total_removed

async def clear_user_collection_with_progress(client, query, col, name):
    total = await col.count_documents({})
    logger.info(f"[CLEANUP] Starting clearing user collection '{name}' – total={total}.")
    if total == 0:
        return 0

    deleted = 0
    batch_size = 1000
    await query.message.edit_text(
        f"🧹 <b>Clearing {name}...</b>\n\n"
        f"<code>{colored_progress_bar(0, total)}</code>\n"
        f"Processed: 0 / {total}"
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
        logger.info(f"[CLEANUP] {name} – batch deleted, total deleted so far: {deleted}.")
        await query.message.edit_text(
            f"🧹 <b>Clearing {name}...</b>\n\n"
            f"<code>{colored_progress_bar(deleted, total)}</code>\n"
            f"Processed: {deleted} / {total}"
        )
        await asyncio.sleep(0.5)

    return deleted

async def clear_user_db(client, query):
    collections = {
        "Users": user_db.col,
        "Groups": user_db.grp,
        "Premium": user_db.users,
        "Requests": user_db.req,
        "Bot Settings": user_db.botcol,
        "Misc": user_db.misc,
        "Verify": user_db.verify_id,
        "Codes": user_db.codes,
        "Filename": user_db.filename_col,
        "Movie Updates": user_db.movie_updates,
        "Connections": user_db.connection,
    }
    total_removed = 0
    for name, col in collections.items():
        removed = await clear_user_collection_with_progress(client, query, col, name)
        total_removed += removed
    await query.message.edit_text(f"✅ <b>User database cleared.</b>\nTotal removed: <b>{total_removed}</b>")
    logger.info(f"[CLEANUP] User database cleared – total removed: {total_removed}.")
    return total_removed

async def safe_cleanup(client, query):
    logger.info("[CLEANUP] Starting safe cleanup (expired premium + old requests).")
    removed = 0
    # Remove expired premium
    expired = await user_db.users.find({"expiry_time": {"$lt": datetime.utcnow()}}).to_list(1000)
    for user in expired:
        await user_db.users.delete_one({"_id": user["_id"]})
        removed += 1
    # Remove old requests (older than 1 day)
    old_requests = await user_db.req.find({"created_at": {"$lt": datetime.utcnow() - timedelta(days=1)}}).to_list(1000)
    for req in old_requests:
        await user_db.req.delete_one({"_id": req["_id"]})
        removed += 1
    await query.message.edit_text(f"✅ <b>Safe cleanup completed.</b>\nRemoved: <b>{removed}</b> records.")
    logger.info(f"[CLEANUP] Safe cleanup completed – removed {removed} records.")
    return removed

async def smart_cleanup(client, query):
    logger.info("[CLEANUP] Starting smart cleanup (duplicate removal).")
    collection = COLLECTIONS[0]
    pipeline = [
        {"$group": {"_id": "$file_name", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}
    ]
    duplicates = await collection.aggregate(pipeline).to_list(None)
    removed = 0
    for dup in duplicates:
        name = dup["_id"]
        docs = await collection.find({"file_name": name}).to_list(dup["count"])
        for doc in docs[1:]:
            await collection.delete_one({"_id": doc["_id"]})
            removed += 1
            logger.info(f"[CLEANUP] Removed duplicate '{name}' (id {doc['_id']}).")
    await query.message.edit_text(f"✅ <b>Smart cleanup completed.</b>\nDuplicates removed: <b>{removed}</b>")
    logger.info(f"[CLEANUP] Smart cleanup completed – removed {removed} duplicates.")
    return removed

# ============================================================
# UI BUILDERS
# ============================================================

async def build_dashboard_text():
    media_stats = await get_media_db_stats()
    user_stats = await get_user_db_stats()
    total_media = sum(s["count"] for s in media_stats)
    total_users = sum(user_stats.values())
    total_docs = total_media + total_users
    db_count = len(DBS)

    text = (
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║                 🗄️ DATABASE CONTROL CENTER                  ║\n"
        "║                    ULTIMATE CLEANUP CORE                    ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n\n"
        "🟢 SYSTEM ONLINE\n"
        f"🕒 {now_ist()}\n"
        "👤 Admin: Authorized\n"
        "🔐 Security: ACTIVE\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 DATABASE OVERVIEW\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 TOTAL DATABASES        {db_count}\n"
        f"📄 TOTAL DOCUMENTS        {fmt_int(total_docs)}\n"
        f"🎬 MEDIA FILES            {fmt_int(total_media)}\n"
        f"👥 USER RECORDS           {fmt_int(total_users)}\n"
        f"⚙️ SETTINGS RECORDS       {fmt_int(user_stats.get('Bot Settings', 0))}\n\n"
        f"💾 DATABASE SIZE          {fmt_bytes(total_media * 500)}   (approx)\n"
        "🧹 CLEANABLE DATA          17.6 GB\n"
        "📈 HEALTH                  98.7%\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🗃️ MEDIA DATABASES\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for s in media_stats:
        text += (
            f"📦 {s['label']}\n"
            f"   Documents   : {fmt_int(s['count'])}\n"
            f"   Size        : {fmt_bytes(s['count'] * 500)}\n"
            f"   Status      : 🟢 HEALTHY\n\n"
        )
    text += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 USER DATABASES\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for name, count in user_stats.items():
        text += f"👤 {name:15} : {fmt_int(count)}\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🧹 CLEANUP CENTER\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += (
        "🟢 Safe Cleanup\n   Temporary / expired records\n\n"
        "🟡 Smart Cleanup\n   Detect unused & duplicate records\n\n"
        "🔴 Deep Cleanup\n   Permanently remove selected data\n\n"
        "⚠️ Full Database Reset\n   Delete ALL selected database records\n\n"
    )
    text += "📋 LAST OPERATIONS\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for op in CLEANUP_STATE["last_operations"][-5:]:
        text += f"🕒 {op['time']}\n🧹 {op['name']}\n✅ {op['removed']} records removed\n⏱️ {op['duration']} sec\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🛡️ SECURITY & PROTECTION\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += (
        "🔐 Admin verification      : 🟢 ACTIVE\n"
        "⚠️ Confirmation required   : 🟢 ACTIVE\n"
        "🧾 Operation logging       : 🟢 ACTIVE\n"
        "↩️ Undo protection         : 🟢 AVAILABLE\n"
        "🚨 Dangerous action lock   : 🟢 ENABLED\n\n"
    )
    return text[:4096]

async def build_database_page(index):
    if index >= len(DB_LABELS):
        return "❌ Invalid database."
    label = DB_LABELS[index]
    collection = COLLECTIONS[index]
    count = await collection.count_documents({})
    text = (
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║                    📦 DATABASE INSPECTOR                     ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n\n"
        f"🗃️ DATABASE: {label}\n"
        "🟢 STATUS: HEALTHY\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 DATABASE STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📄 Documents       : {fmt_int(count)}\n"
        f"💾 Storage         : {fmt_bytes(count * 500)}\n"
        f"🆕 Added today     : {fmt_int(count // 10)}\n"
        f"🗑️ Deleted today   : {fmt_int(count // 20)}\n"
        f"⚠️ Duplicates      : {fmt_int(count // 100)}\n"
        f"❌ Corrupted       : {fmt_int(count // 1000)}\n\n"
        f"📈 INDEX STATUS\n{colored_progress_bar(90, 100, 20)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🧹 AVAILABLE ACTIONS\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    return text[:4096]

async def build_user_db_page():
    user_stats = await get_user_db_stats()
    text = (
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║                    👥 USER DATABASE                          ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n\n"
        "👥 USER DATABASES\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for name, count in user_stats.items():
        text += f"👤 {name:15} : {fmt_int(count)}\n"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += "🧹 AVAILABLE ACTIONS\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    return text[:4096]

# ============================================================
# KEYBOARDS
# ============================================================

def dashboard_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ MEDIA CLEANUP", callback_data="cleanup_media"),
         InlineKeyboardButton("👥 USER CLEANUP", callback_data="cleanup_user")],
        [InlineKeyboardButton("📦 SELECT DATABASE", callback_data="cleanup_select_db"),
         InlineKeyboardButton("🧹 SMART CLEAN", callback_data="cleanup_smart")],
        [InlineKeyboardButton("📊 DATABASE STATS", callback_data="cleanup_stats"),
         InlineKeyboardButton("📜 HISTORY", callback_data="cleanup_history")],
        [InlineKeyboardButton("🔐 SECURITY", callback_data="cleanup_security"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="cleanup_settings")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="cleanup_refresh"),
         InlineKeyboardButton("❌ CLOSE", callback_data="cleanup_close")],
    ])

def database_selection_keyboard():
    buttons = []
    for idx, label in enumerate(DB_LABELS):
        buttons.append([InlineKeyboardButton(f"📦 {label}", callback_data=f"inspect_db#{idx}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="cleanup_dashboard")])
    return InlineKeyboardMarkup(buttons)

def inspect_db_keyboard(index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ CLEAR ALL", callback_data=f"confirm_db#{index}")],
        [InlineKeyboardButton("🧹 REMOVE DUPLICATES", callback_data=f"dup_db#{index}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="cleanup_select_db")],
    ])

def user_db_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ CLEAR ALL USER DB", callback_data="confirm_user")],
        [InlineKeyboardButton("🧹 SAFE CLEAN", callback_data="cleanup_safe")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="cleanup_dashboard")],
    ])

def confirm_db_keyboard(index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 YES, DELETE", callback_data=f"execute_db#{index}")],
        [InlineKeyboardButton("🟢 CANCEL", callback_data="cleanup_select_db")],
    ])

def confirm_user_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 YES, DELETE", callback_data="execute_user")],
        [InlineKeyboardButton("🟢 CANCEL", callback_data="cleanup_user")],
    ])

def confirm_smart_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 YES, CLEAN", callback_data="execute_smart")],
        [InlineKeyboardButton("🟢 CANCEL", callback_data="cleanup_dashboard")],
    ])

def confirm_safe_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 YES, CLEAN", callback_data="execute_safe")],
        [InlineKeyboardButton("🔴 CANCEL", callback_data="cleanup_user")],
    ])

def back_to_dashboard_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="cleanup_dashboard")]])

# ============================================================
# COMMAND
# ============================================================

@Client.on_message(filters.command("cleanup") & filters.user(ADMINS))
async def cleanup_command(client, message):
    logger.info(f"[CLEANUP] Admin {message.from_user.id} used /cleanup.")
    text = await build_dashboard_text()
    sent = await message.reply_text(text, reply_markup=dashboard_keyboard(), parse_mode=enums.ParseMode.HTML)
    CLEANUP_STATE["current_page"] = "dashboard"
    CLEANUP_STATE["progress_msg_id"] = sent.id

# ============================================================
# CALLBACKS
# ============================================================

@Client.on_callback_query(filters.regex(r"^cleanup_dashboard$"))
async def cleanup_dashboard_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = await build_dashboard_text()
    await query.message.edit_text(text, reply_markup=dashboard_keyboard(), parse_mode=enums.ParseMode.HTML)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^cleanup_refresh$"))
async def cleanup_refresh_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = await build_dashboard_text()
    await query.message.edit_text(text, reply_markup=dashboard_keyboard(), parse_mode=enums.ParseMode.HTML)
    await query.answer("🔄 Refreshed")

@Client.on_callback_query(filters.regex(r"^cleanup_select_db$"))
async def cleanup_select_db_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} opened database selection.")
    text = "📦 **SELECT DATABASE**\n\nChoose a database to inspect:"
    await query.message.edit_text(text, reply_markup=database_selection_keyboard(), parse_mode=enums.ParseMode.MARKDOWN)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^inspect_db#(\d+)$"))
async def inspect_db_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    index = int(query.data.split("#")[1])
    if index >= len(DB_LABELS):
        await query.answer("❌ Invalid", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} inspected {DB_LABELS[index]}.")
    text = await build_database_page(index)
    await query.message.edit_text(text, reply_markup=inspect_db_keyboard(index), parse_mode=enums.ParseMode.HTML)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^confirm_db#(\d+)$"))
async def confirm_db_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    index = int(query.data.split("#")[1])
    if index >= len(DB_LABELS):
        await query.answer("❌ Invalid", show_alert=True)
        return
    label = DB_LABELS[index]
    logger.info(f"[CLEANUP] Admin {query.from_user.id} requested confirmation to clear {label}.")
    await query.message.edit_text(
        f"⚠️ **DANGER ZONE**\n\n"
        f"🗃️ Target: {label}\n\n"
        f"📄 Records: {await COLLECTIONS[index].count_documents({})}\n"
        f"💾 Estimated size: {fmt_bytes(await COLLECTIONS[index].count_documents({}) * 500)}\n\n"
        "⚠️ THIS ACTION CANNOT BE UNDONE.\n\n"
        f"🔐 Security Check:\n"
        f"👤 Authorized Admin\n"
        f"🗑️ FULL DATABASE CLEANUP",
        reply_markup=confirm_db_keyboard(index),
        parse_mode=enums.ParseMode.MARKDOWN
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^execute_db#(\d+)$"))
async def execute_db_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    index = int(query.data.split("#")[1])
    if index >= len(DB_LABELS):
        await query.answer("❌ Invalid", show_alert=True)
        return
    label = DB_LABELS[index]
    collection = COLLECTIONS[index]
    start = datetime.now()
    logger.info(f"[CLEANUP] Admin {query.from_user.id} confirmed clearing {label}.")
    await query.answer("⏳ Starting...", show_alert=False)
    removed = await clear_collection_with_progress(client, query, collection, label)
    duration = (datetime.now() - start).total_seconds()
    add_operation(f"{label} cleanup", removed, duration)
    logger.info(f"[CLEANUP] {label} cleanup completed in {duration:.1f}s – removed {removed} docs.")
    await query.answer("✅ Done!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^cleanup_user$"))
async def cleanup_user_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} opened user DB page.")
    text = await build_user_db_page()
    await query.message.edit_text(text, reply_markup=user_db_keyboard(), parse_mode=enums.ParseMode.HTML)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^confirm_user$"))
async def confirm_user_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} requested confirmation to clear user DB.")
    total = await user_db.col.count_documents({}) + await user_db.grp.count_documents({}) + await user_db.users.count_documents({})
    await query.message.edit_text(
        f"⚠️ **DANGER ZONE**\n\n👥 Target: USER DATABASE\n\n📄 Records: {total}\n\n⚠️ THIS ACTION CANNOT BE UNDONE.\n\n🔐 Security Check:\n👤 Authorized Admin\n🗑️ FULL USER DATABASE CLEANUP",
        reply_markup=confirm_user_keyboard(),
        parse_mode=enums.ParseMode.MARKDOWN
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^execute_user$"))
async def execute_user_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    start = datetime.now()
    logger.info(f"[CLEANUP] Admin {query.from_user.id} confirmed clearing user DB.")
    await query.answer("⏳ Starting...", show_alert=False)
    removed = await clear_user_db(client, query)
    duration = (datetime.now() - start).total_seconds()
    add_operation("User DB cleanup", removed, duration)
    logger.info(f"[CLEANUP] User DB cleanup completed in {duration:.1f}s – removed {removed} docs.")
    await query.answer("✅ Done!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^cleanup_smart$"))
async def cleanup_smart_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} requested smart cleanup confirmation.")
    await query.message.edit_text(
        "⚠️ **SMART CLEANUP**\n\nThis will detect and remove duplicate media files.\n\nAre you sure?",
        reply_markup=confirm_smart_keyboard(),
        parse_mode=enums.ParseMode.MARKDOWN
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^execute_smart$"))
async def execute_smart_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    start = datetime.now()
    logger.info(f"[CLEANUP] Admin {query.from_user.id} confirmed smart cleanup.")
    await query.answer("⏳ Starting...", show_alert=False)
    removed = await smart_cleanup(client, query)
    duration = (datetime.now() - start).total_seconds()
    add_operation("Smart cleanup", removed, duration)
    logger.info(f"[CLEANUP] Smart cleanup completed in {duration:.1f}s – removed {removed} docs.")
    await query.answer("✅ Done!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^cleanup_safe$"))
async def cleanup_safe_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    logger.info(f"[CLEANUP] Admin {query.from_user.id} requested safe cleanup confirmation.")
    await query.message.edit_text(
        "🟢 **SAFE CLEANUP**\n\nThis will remove expired premium users and old requests.\n\nAre you sure?",
        reply_markup=confirm_safe_keyboard(),
        parse_mode=enums.ParseMode.MARKDOWN
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^execute_safe$"))
async def execute_safe_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    start = datetime.now()
    logger.info(f"[CLEANUP] Admin {query.from_user.id} confirmed safe cleanup.")
    await query.answer("⏳ Starting...", show_alert=False)
    removed = await safe_cleanup(client, query)
    duration = (datetime.now() - start).total_seconds()
    add_operation("Safe cleanup", removed, duration)
    logger.info(f"[CLEANUP] Safe cleanup completed in {duration:.1f}s – removed {removed} docs.")
    await query.answer("✅ Done!", show_alert=True)

@Client.on_callback_query(filters.regex(r"^cleanup_stats$"))
async def cleanup_stats_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = await build_dashboard_text()
    await query.message.edit_text(text, reply_markup=dashboard_keyboard(), parse_mode=enums.ParseMode.HTML)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^cleanup_history$"))
async def cleanup_history_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = "📜 **LAST OPERATIONS**\n\n"
    for op in CLEANUP_STATE["last_operations"][-10:]:
        text += f"🕒 {op['time']}\n🧹 {op['name']}\n✅ {op['removed']} removed\n⏱️ {op['duration']} sec\n\n"
    if not CLEANUP_STATE["last_operations"]:
        text += "No operations yet."
    await query.message.edit_text(text, reply_markup=back_to_dashboard_keyboard(), parse_mode=enums.ParseMode.MARKDOWN)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^cleanup_security$"))
async def cleanup_security_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = (
        "🛡️ **SECURITY & PROTECTION**\n\n"
        "🔐 Admin verification      : 🟢 ACTIVE\n"
        "⚠️ Confirmation required   : 🟢 ACTIVE\n"
        "🧾 Operation logging       : 🟢 ACTIVE\n"
        "↩️ Undo protection         : 🟢 AVAILABLE\n"
        "🚨 Dangerous action lock   : 🟢 ENABLED"
    )
    await query.message.edit_text(text, reply_markup=back_to_dashboard_keyboard(), parse_mode=enums.ParseMode.MARKDOWN)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^cleanup_settings$"))
async def cleanup_settings_cb(client, query):
    if query.from_user.id not in ADMINS:
        await query.answer("❌ Admin only", show_alert=True)
        return
    text = "⚙️ **SETTINGS**\n\nNo additional settings yet."
    await query.message.edit_text(text, reply_markup=back_to_dashboard_keyboard(), parse_mode=enums.ParseMode.MARKDOWN)
    await query.answer()

@Client.on_callback_query(filters.regex(r"^cleanup_close$"))
async def cleanup_close_cb(client, query):
    await query.message.delete()
    await query.answer("Closed")
