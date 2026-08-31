"""
bot/handlers/admin.py

ULTIMATE ADMIN HANDLER – Full live dashboard, tracking, and management.
All buttons in CAPITALS for a clean, professional look.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import psutil
from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Imports – tolerant to missing services
# ----------------------------------------------------------------------------

try:
    from bot.database.core import db
except ImportError:
    db = None

try:
    from bot.database.users import user_db
except ImportError:
    user_db = None

try:
    from bot.database.groups import group_db
except ImportError:
    group_db = None

try:
    from bot.database.premium import premium_db
except ImportError:
    premium_db = None

try:
    from bot.services.broadcast import users_broadcast, groups_broadcast
except ImportError:
    users_broadcast = None
    groups_broadcast = None

try:
    from bot.services.file_search import file_search
except ImportError:
    file_search = None

try:
    from bot.services.settings import get_settings, save_group_settings
except ImportError:
    get_settings = None
    save_group_settings = None

# ----------------------------------------------------------------------------
# Admin authorisation
# ----------------------------------------------------------------------------

ADMINS = list(map(int, os.getenv("ADMINS", "").split())) if os.getenv("ADMINS") else []

def is_admin(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    try:
        return int(user_id) in [int(x) for x in ADMINS]
    except Exception:
        return False

def admin_only():
    return filters.user(ADMINS)

# ----------------------------------------------------------------------------
# State and caching
# ----------------------------------------------------------------------------

admin_states: Dict[int, Dict] = {}
admin_operation_lock = asyncio.Lock()

_cached_stats: Dict[str, Any] = {
    "users": 0,
    "groups": 0,
    "premium": 0,
    "searches": 0,
    "uploads": 0,
    "errors": 0,
    "total_size_mb": 0,
    "last_updated": None,
}
_last_stats_refresh = 0
STATS_REFRESH_INTERVAL = 60

_recent_logs: List[Dict[str, Any]] = []
MAX_LOGS = 50

_search_stats: Dict[str, Any] = {
    "total_searches": 0,
    "popular_queries": {},
    "zero_result_queries": {},
}
_search_stats_lock = asyncio.Lock()

_upload_stats: Dict[str, Any] = {
    "total_uploads": 0,
    "recent_uploads": [],
    "total_size_bytes": 0,
}
_upload_stats_lock = asyncio.Lock()

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------

def format_number(value) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"

def format_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    elif bytes_ < 1024 ** 2:
        return f"{bytes_ / 1024:.1f} KB"
    elif bytes_ < 1024 ** 3:
        return f"{bytes_ / 1024 ** 2:.1f} MB"
    else:
        return f"{bytes_ / 1024 ** 3:.2f} GB"

def format_datetime(dt: Optional[datetime]) -> str:
    if not dt:
        return "N/A"
    try:
        return dt.strftime("%d %b %Y, %H:%M:%S")
    except Exception:
        return str(dt)

def get_uptime() -> str:
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    except Exception:
        return "N/A"

async def safe_answer(query: CallbackQuery, text: str = "", show_alert: bool = False):
    try:
        await query.answer(text, show_alert=show_alert)
    except Exception:
        pass

async def safe_edit(query: CallbackQuery, text: str, reply_markup=None):
    try:
        await query.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Failed to edit admin message")

def log_operation(op_type: str, details: str, user_id: Optional[int] = None, status: str = "success"):
    entry = {
        "timestamp": datetime.utcnow(),
        "type": op_type,
        "details": details,
        "user_id": user_id,
        "status": status,
    }
    _recent_logs.append(entry)
    if len(_recent_logs) > MAX_LOGS:
        _recent_logs.pop(0)

# ----------------------------------------------------------------------------
# Stats collection (cached)
# ----------------------------------------------------------------------------

async def collect_stats(force: bool = False) -> Dict[str, Any]:
    global _last_stats_refresh, _cached_stats
    now = time.time()
    if not force and (now - _last_stats_refresh) < STATS_REFRESH_INTERVAL:
        return _cached_stats

    stats = {
        "users": 0,
        "groups": 0,
        "premium": 0,
        "searches": 0,
        "uploads": 0,
        "errors": 0,
        "total_size_mb": 0,
        "last_updated": datetime.utcnow(),
    }

    try:
        if user_db and hasattr(user_db, "total_users_count"):
            stats["users"] = await user_db.total_users_count()
        elif db and hasattr(db, "total_users_count"):
            stats["users"] = await db.total_users_count()
    except Exception:
        pass

    try:
        if group_db and hasattr(group_db, "total_chat_count"):
            stats["groups"] = await group_db.total_chat_count()
        elif db and hasattr(db, "total_chat_count"):
            stats["groups"] = await db.total_chat_count()
    except Exception:
        pass

    try:
        if premium_db and hasattr(premium_db, "all_premium_users"):
            stats["premium"] = await premium_db.all_premium_users()
        elif db and hasattr(db, "all_premium_users"):
            stats["premium"] = await db.all_premium_users()
    except Exception:
        pass

    if file_search and hasattr(file_search, "get_stats"):
        try:
            s = await file_search.get_stats()
            stats["searches"] = s.get("total_searches", 0)
        except Exception:
            pass

    async with _upload_stats_lock:
        stats["uploads"] = _upload_stats.get("total_uploads", 0)
        stats["total_size_mb"] = _upload_stats.get("total_size_bytes", 0) / (1024 * 1024)

    stats["errors"] = sum(1 for log in _recent_logs if log.get("status") == "error")

    _cached_stats = stats
    _last_stats_refresh = now
    return stats

async def get_index_status() -> Dict[str, Any]:
    status = {
        "text_index_exists": False,
        "field_indexes": {},
        "message": "Not checked",
    }
    try:
        if db and hasattr(db, "collection"):
            collection = db.collection("media_files")
            indexes = await collection.index_information()
            status["text_index_exists"] = "search_text_index" in indexes
            status["field_indexes"] = {k: v for k, v in indexes.items() if k != "_id_"}
            status["message"] = "OK"
        else:
            status["message"] = "Database not available"
    except Exception as e:
        status["message"] = f"Error: {e}"
    return status

# ----------------------------------------------------------------------------
# Keyboard builders (ALL CAPS BUTTONS)
# ----------------------------------------------------------------------------

def main_dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 LIVE DASHBOARD", callback_data="admin#dashboard")],
        [InlineKeyboardButton("👥 USERS", callback_data="admin#users"),
         InlineKeyboardButton("💬 GROUPS", callback_data="admin#groups")],
        [InlineKeyboardButton("💎 PREMIUM", callback_data="admin#premium"),
         InlineKeyboardButton("📂 FILES", callback_data="admin#files")],
        [InlineKeyboardButton("🔎 SEARCH ANALYTICS", callback_data="admin#search"),
         InlineKeyboardButton("📡 INDEXING", callback_data="admin#indexing")],
        [InlineKeyboardButton("📤 UPLOAD TRACKING", callback_data="admin#uploads"),
         InlineKeyboardButton("📋 DATABASE LOGS", callback_data="admin#logs")],
        [InlineKeyboardButton("🖥️ SYSTEM HEALTH", callback_data="admin#health"),
         InlineKeyboardButton("🔧 MAINTENANCE", callback_data="admin#maintenance")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin#broadcast"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="admin#settings")],
        [InlineKeyboardButton("🔄 REFRESH ALL", callback_data="admin#refresh")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
    ])

def back_button(callback: str = "admin#home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ BACK", callback_data=callback)],
        [InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
    ])

def dynamic_back(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ BACK", callback_data=callback)],
        [InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
    ])

# ----------------------------------------------------------------------------
# /admin command (main entry)
# ----------------------------------------------------------------------------

@Client.on_message(
    filters.command("admin") & filters.private & filters.incoming & admin_only()
)
async def admin_panel(client: Client, message: Message):
    await message.reply_text(
        "<b>🛠 ADMINISTRATOR PANEL</b>\n\n"
        "Welcome to the ultimate control center.\n"
        "Choose an action below.",
        reply_markup=main_dashboard_keyboard(),
    )

# ----------------------------------------------------------------------------
# Dashboard (live stats)
# ----------------------------------------------------------------------------

async def render_dashboard() -> str:
    stats = await collect_stats()
    uptime = get_uptime()
    text = (
        "<b>📊 LIVE DASHBOARD</b>\n\n"
        f"👤 <b>USERS:</b> {format_number(stats['users'])}\n"
        f"💬 <b>GROUPS:</b> {format_number(stats['groups'])}\n"
        f"💎 <b>PREMIUM:</b> {format_number(stats['premium'])}\n"
        f"🔎 <b>SEARCHES:</b> {format_number(stats['searches'])}\n"
        f"📤 <b>UPLOADS:</b> {format_number(stats['uploads'])}\n"
        f"📦 <b>TOTAL SIZE:</b> {stats['total_size_mb']:.1f} MB\n"
        f"❌ <b>ERRORS (last 50 ops):</b> {format_number(stats['errors'])}\n\n"
        f"⏱️ <b>UPTIME:</b> {uptime}\n"
        f"🕐 <b>UPDATED:</b> {format_datetime(stats['last_updated'])} UTC"
    )
    return text

@Client.on_callback_query(filters.regex(r"^admin#dashboard$"))
async def dashboard_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_dashboard()
    await safe_edit(
        query,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="admin#dashboard_refresh")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="admin#home"),
             InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
        ])
    )

@Client.on_callback_query(filters.regex(r"^admin#dashboard_refresh$"))
async def dashboard_refresh(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await collect_stats(force=True)
    await safe_answer(query, "Refreshed.")
    text = await render_dashboard()
    await safe_edit(
        query,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="admin#dashboard_refresh")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="admin#home"),
             InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
        ])
    )

# ----------------------------------------------------------------------------
# Search Analytics
# ----------------------------------------------------------------------------

async def render_search_analytics() -> str:
    if not file_search:
        return "❌ File search service not available."
    stats = await file_search.get_stats()
    text = (
        "<b>🔎 SEARCH ANALYTICS</b>\n\n"
        f"TOTAL SEARCHES: {format_number(stats.get('total_searches', 0))}\n"
        f"UNIQUE QUERIES: {format_number(stats.get('unique_queries', 0))}\n"
        f"CACHE HITS: {format_number(stats.get('cache_hits', 0))}\n"
        f"CACHE MISSES: {format_number(stats.get('cache_misses', 0))}\n\n"
        "<b>TOP 10 POPULAR QUERIES:</b>\n"
    )
    popular = stats.get("popular_queries", {})
    for query, count in list(popular.items())[:10]:
        text += f"  • <code>{query}</code> – {count}\n"
    text += "\n<b>TOP 10 ZERO‑RESULT QUERIES:</b>\n"
    zero = stats.get("zero_result_queries", {})
    for query, count in list(zero.items())[:10]:
        text += f"  • <code>{query}</code> – {count}\n"
    return text

@Client.on_callback_query(filters.regex(r"^admin#search$"))
async def search_analytics_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_search_analytics()
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Indexing Status
# ----------------------------------------------------------------------------

async def render_indexing_status() -> str:
    status = await get_index_status()
    text = (
        "<b>📡 INDEXING STATUS</b>\n\n"
        f"TEXT INDEX EXISTS: {'✅' if status['text_index_exists'] else '❌'}\n"
        f"INDEXES FOUND: {len(status['field_indexes'])}\n"
        f"MESSAGE: {status['message']}\n\n"
        "ACTIONS:"
    )
    return text

@Client.on_callback_query(filters.regex(r"^admin#indexing$"))
async def indexing_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_indexing_status()
    await safe_edit(
        query,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REBUILD INDEX", callback_data="admin#index_rebuild")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="admin#home"),
             InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
        ])
    )

@Client.on_callback_query(filters.regex(r"^admin#index_rebuild$"))
async def rebuild_index_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query, "Rebuilding indexes...")
    if file_search and hasattr(file_search, "rebuild_indexes"):
        success = await file_search.rebuild_indexes()
        if success:
            await safe_edit(query, "✅ INDEXES REBUILT SUCCESSFULLY.", back_button("admin#home"))
        else:
            await safe_edit(query, "❌ INDEX REBUILD FAILED. CHECK LOGS.", back_button("admin#home"))
    else:
        await safe_edit(query, "❌ FILE SEARCH SERVICE NOT AVAILABLE.", back_button("admin#home"))

# ----------------------------------------------------------------------------
# Upload Tracking
# ----------------------------------------------------------------------------

async def render_upload_tracking() -> str:
    async with _upload_stats_lock:
        total = _upload_stats.get("total_uploads", 0)
        total_size = _upload_stats.get("total_size_bytes", 0)
        recent = _upload_stats.get("recent_uploads", [])[-10:]
    text = (
        "<b>📤 UPLOAD TRACKING</b>\n\n"
        f"TOTAL UPLOADS: {format_number(total)}\n"
        f"TOTAL SIZE: {format_size(total_size)}\n\n"
        "<b>RECENT UPLOADS:</b>\n"
    )
    if not recent:
        text += "  No recent uploads."
    else:
        for entry in reversed(recent):
            filename = entry.get("filename", "Unknown")
            size = entry.get("size", 0)
            user = entry.get("user_id", "N/A")
            time_str = format_datetime(entry.get("timestamp"))
            text += f"  • <code>{filename}</code> ({format_size(size)}) – USER {user} at {time_str}\n"
    return text

@Client.on_callback_query(filters.regex(r"^admin#uploads$"))
async def uploads_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_upload_tracking()
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Database Logs
# ----------------------------------------------------------------------------

async def render_logs() -> str:
    if not _recent_logs:
        return "<b>📋 DATABASE LOGS</b>\n\nNo recent operations."
    text = "<b>📋 DATABASE LOGS (LAST 20)</b>\n\n"
    for entry in reversed(_recent_logs[-20:]):
        time_str = format_datetime(entry.get("timestamp"))
        status_icon = "✅" if entry.get("status") == "success" else "❌"
        text += f"• {time_str} – {status_icon} {entry.get('type')} – {entry.get('details')}\n"
    return text

@Client.on_callback_query(filters.regex(r"^admin#logs$"))
async def logs_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_logs()
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# System Health
# ----------------------------------------------------------------------------

async def render_system_health() -> str:
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime = get_uptime()
        text = (
            "<b>🖥️ SYSTEM HEALTH</b>\n\n"
            f"⏱️ UPTIME: {uptime}\n"
            f"💻 CPU: {cpu:.1f}%\n"
            f"🧠 RAM: {mem.used / 1024 ** 3:.1f} GB / {mem.total / 1024 ** 3:.1f} GB ({mem.percent:.0f}%)\n"
            f"💾 DISK: {disk.used / 1024 ** 3:.1f} GB / {disk.total / 1024 ** 3:.1f} GB ({disk.percent:.0f}%)\n"
            f"🐍 PYTHON: {sys.version.split()[0]}\n"
            f"📦 PYROGRAM: {getattr(sys.modules.get('pyrogram'), '__version__', 'N/A')}"
        )
    except Exception as e:
        text = f"❌ Error collecting system stats: {e}"
    return text

@Client.on_callback_query(filters.regex(r"^admin#health$"))
async def health_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_system_health()
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# User Management – list users
# ----------------------------------------------------------------------------

async def render_users_list(page: int = 0) -> str:
    users = []
    try:
        if user_db and hasattr(user_db, "get_all_users"):
            async for user in user_db.get_all_users():
                users.append(user)
        elif db and hasattr(db, "get_all_users"):
            async for user in db.get_all_users():
                users.append(user)
    except Exception as e:
        return f"❌ Error fetching users: {e}"
    if not users:
        return "No users found."
    page_size = 10
    start = page * page_size
    end = start + page_size
    page_users = users[start:end]
    if not page_users:
        return "No more users."
    total_pages = (len(users) + page_size - 1) // page_size
    text = f"<b>👥 USERS (page {page+1}/{total_pages})</b>\n\n"
    for user in page_users:
        user_id = user.get("user_id") or user.get("id")
        name = user.get("first_name", "") or user.get("name", "Unknown")
        text += f"• <code>{user_id}</code> – {name}\n"
    # Pagination buttons
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin#users_page:{page-1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin#users_page:{page+1}"))
    return text, InlineKeyboardMarkup([buttons]) if buttons else None

@Client.on_callback_query(filters.regex(r"^admin#users$"))
async def users_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text, keyboard = await render_users_list(0)
    await safe_edit(query, text, keyboard or back_button("admin#home"))

@Client.on_callback_query(filters.regex(r"^admin#users_page:"))
async def users_page_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    page = int(query.data.split(":")[2])
    text, keyboard = await render_users_list(page)
    await safe_edit(query, text, keyboard or back_button("admin#home"))

# ----------------------------------------------------------------------------
# Groups list (similar with pagination)
# ----------------------------------------------------------------------------

async def render_groups_list(page: int = 0) -> str:
    groups = []
    try:
        if group_db and hasattr(group_db, "get_all_chats"):
            async for g in group_db.get_all_chats():
                groups.append(g)
        elif db and hasattr(db, "get_all_chats"):
            async for g in db.get_all_chats():
                groups.append(g)
    except Exception as e:
        return f"❌ Error fetching groups: {e}"
    if not groups:
        return "No groups found."
    page_size = 10
    start = page * page_size
    end = start + page_size
    page_groups = groups[start:end]
    if not page_groups:
        return "No more groups."
    total_pages = (len(groups) + page_size - 1) // page_size
    text = f"<b>💬 GROUPS (page {page+1}/{total_pages})</b>\n\n"
    for g in page_groups:
        chat_id = g.get("chat_id") or g.get("id")
        title = g.get("title", "Unknown")
        text += f"• <code>{chat_id}</code> – {title}\n"
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️ PREV", callback_data=f"admin#groups_page:{page-1}"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"admin#groups_page:{page+1}"))
    return text, InlineKeyboardMarkup([buttons]) if buttons else None

@Client.on_callback_query(filters.regex(r"^admin#groups$"))
async def groups_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text, keyboard = await render_groups_list(0)
    await safe_edit(query, text, keyboard or back_button("admin#home"))

@Client.on_callback_query(filters.regex(r"^admin#groups_page:"))
async def groups_page_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    page = int(query.data.split(":")[2])
    text, keyboard = await render_groups_list(page)
    await safe_edit(query, text, keyboard or back_button("admin#home"))

# ----------------------------------------------------------------------------
# Files management (list recent files)
# ----------------------------------------------------------------------------

async def render_files_list() -> str:
    if not file_search or not hasattr(file_search, "search"):
        return "❌ File search service not available."
    try:
        results = await file_search.search("", limit=20, score_threshold=0)
        if not results:
            return "No files found."
        text = "<b>📂 RECENT FILES (LAST 20)</b>\n\n"
        for i, r in enumerate(results, 1):
            text += f"{i}. <code>{r.file_name[:60]}</code> – {format_size(r.file_size or 0)} – ID: {r.file_id}\n"
        return text
    except Exception as e:
        return f"❌ Error: {e}"

@Client.on_callback_query(filters.regex(r"^admin#files$"))
async def files_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = await render_files_list()
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Premium management
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#premium$"))
async def premium_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    stats = await collect_stats()
    text = (
        "<b>💎 PREMIUM MANAGEMENT</b>\n\n"
        f"ACTIVE PREMIUM USERS: {format_number(stats['premium'])}\n\n"
        "COMMANDS:\n"
        "<code>/addpremium USER_ID DAYS</code>\n"
        "<code>/delpremium USER_ID</code>"
    )
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Maintenance
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#maintenance$"))
async def maintenance_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = (
        "<b>🔧 MAINTENANCE MODE</b>\n\n"
        "Toggle maintenance mode or view status."
    )
    await safe_edit(
        query,
        text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ENABLE", callback_data="maintenance#on"),
             InlineKeyboardButton("🔴 DISABLE", callback_data="maintenance#off")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="admin#home"),
             InlineKeyboardButton("❌ CLOSE", callback_data="admin#close")],
        ])
    )

# ----------------------------------------------------------------------------
# Broadcast
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#broadcast$"))
async def broadcast_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = (
        "<b>📢 BROADCAST</b>\n\n"
        "Reply to a message and use:\n"
        "<code>/broadcast</code>"
    )
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#settings$"))
async def settings_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    text = (
        "<b>⚙️ BOT SETTINGS</b>\n\n"
        "Group-specific settings should be managed via the settings service."
    )
    await safe_edit(query, text, back_button("admin#home"))

# ----------------------------------------------------------------------------
# Refresh All
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#refresh$"))
async def refresh_all_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await collect_stats(force=True)
    await safe_answer(query, "All stats refreshed.")
    await safe_edit(
        query,
        "<b>🔄 REFRESH COMPLETE</b>\n\nAll dashboard data has been updated.",
        main_dashboard_keyboard(),
    )

# ----------------------------------------------------------------------------
# Home and Close
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^admin#home$"))
async def home_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    await safe_edit(
        query,
        "<b>🛠 ADMINISTRATOR PANEL</b>\n\nChoose an action below.",
        main_dashboard_keyboard(),
    )

@Client.on_callback_query(filters.regex(r"^admin#close$"))
async def close_callback(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    await safe_answer(query)
    try:
        await query.message.delete()
    except Exception:
        pass

# ----------------------------------------------------------------------------
# Command handlers (text commands)
# ----------------------------------------------------------------------------

@Client.on_message(
    filters.command("dashboard") & filters.private & filters.incoming & admin_only()
)
async def dashboard_command(client: Client, message: Message):
    text = await render_dashboard()
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="admin#dashboard_refresh")],
            [InlineKeyboardButton("⬅️ BACK TO ADMIN", callback_data="admin#home")],
        ])
    )

@Client.on_message(
    filters.command("stats") & filters.private & filters.incoming & admin_only()
)
async def stats_command(client: Client, message: Message):
    stats = await collect_stats()
    text = (
        "<b>📊 BOT STATISTICS</b>\n\n"
        f"👤 USERS: <code>{format_number(stats['users'])}</code>\n"
        f"💬 GROUPS: <code>{format_number(stats['groups'])}</code>\n"
        f"💎 PREMIUM: <code>{format_number(stats['premium'])}</code>\n"
        f"🔎 SEARCHES: <code>{format_number(stats['searches'])}</code>\n"
        f"📤 UPLOADS: <code>{format_number(stats['uploads'])}</code>\n"
        f"📦 TOTAL SIZE: <code>{stats['total_size_mb']:.1f} MB</code>\n"
        f"❌ ERRORS: <code>{format_number(stats['errors'])}</code>"
    )
    await message.reply_text(text, reply_markup=back_button("admin#home"))

@Client.on_message(
    filters.command("users") & filters.private & filters.incoming & admin_only()
)
async def users_command(client: Client, message: Message):
    stats = await collect_stats()
    await message.reply_text(
        f"<b>👥 USER STATISTICS</b>\n\nTOTAL USERS: <code>{format_number(stats['users'])}</code>",
        reply_markup=back_button("admin#home")
    )

@Client.on_message(
    filters.command("groups") & filters.private & filters.incoming & admin_only()
)
async def groups_command(client: Client, message: Message):
    stats = await collect_stats()
    await message.reply_text(
        f"<b>💬 GROUP STATISTICS</b>\n\nTOTAL GROUPS: <code>{format_number(stats['groups'])}</code>",
        reply_markup=back_button("admin#home")
    )

@Client.on_message(
    filters.command("ban") & filters.private & filters.incoming & admin_only()
)
async def ban_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/ban USER_ID [reason]</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")
    reason = " ".join(message.command[2:]).strip() or "No Reason"
    try:
        if user_db and hasattr(user_db, "ban_user"):
            await user_db.ban_user(user_id, reason)
        elif db and hasattr(db, "ban_user"):
            await db.ban_user(user_id, reason)
        else:
            return await message.reply_text("❌ User database service unavailable.")
        await message.reply_text(
            f"<b>🚫 USER BANNED</b>\n\nUSER ID: <code>{user_id}</code>\nREASON: <code>{reason}</code>",
            reply_markup=back_button("admin#home")
        )
    except Exception as e:
        await message.reply_text(f"❌ Failed to ban user.\n<code>{e}</code>")

@Client.on_message(
    filters.command("unban") & filters.private & filters.incoming & admin_only()
)
async def unban_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/unban USER_ID</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")
    try:
        if user_db and hasattr(user_db, "remove_ban"):
            await user_db.remove_ban(user_id)
        elif db and hasattr(db, "remove_ban"):
            await db.remove_ban(user_id)
        else:
            return await message.reply_text("❌ User database service unavailable.")
        await message.reply_text(f"✅ USER <code>{user_id}</code> HAS BEEN UNBANNED.", reply_markup=back_button("admin#home"))
    except Exception as e:
        await message.reply_text(f"❌ Failed to unban user.\n<code>{e}</code>")

@Client.on_message(
    filters.command("addpremium") & filters.private & filters.incoming & admin_only()
)
async def add_premium_command(client: Client, message: Message):
    if len(message.command) < 3:
        return await message.reply_text("Usage: <code>/addpremium USER_ID DAYS</code>")
    try:
        user_id = int(message.command[1])
        days = int(message.command[2])
        if days <= 0: raise ValueError
    except ValueError:
        return await message.reply_text("❌ Invalid user ID or days.")
    expiry = datetime.utcnow() + timedelta(days=days)
    try:
        if premium_db and hasattr(premium_db, "update_user"):
            await premium_db.update_user({"id": user_id, "expiry_time": expiry})
        elif db and hasattr(db, "update_user"):
            await db.update_user({"id": user_id, "expiry_time": expiry})
        else:
            return await message.reply_text("❌ Premium database service unavailable.")
        await message.reply_text(
            f"<b>💎 PREMIUM ACTIVATED</b>\n\nUSER ID: <code>{user_id}</code>\nDURATION: <code>{days} days</code>\nEXPIRES: <code>{format_datetime(expiry)} UTC</code>",
            reply_markup=back_button("admin#home")
        )
    except Exception as e:
        await message.reply_text(f"❌ Failed to add premium.\n<code>{e}</code>")

@Client.on_message(
    filters.command("delpremium") & filters.private & filters.incoming & admin_only()
)
async def del_premium_command(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/delpremium USER_ID</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID.")
    try:
        if premium_db and hasattr(premium_db, "remove_premium_access"):
            await premium_db.remove_premium_access(user_id)
        elif db and hasattr(db, "remove_premium_access"):
            await db.remove_premium_access(user_id)
        else:
            return await message.reply_text("❌ Premium database service unavailable.")
        await message.reply_text(f"✅ PREMIUM ACCESS REMOVED FROM <code>{user_id}</code>.", reply_markup=back_button("admin#home"))
    except Exception as e:
        await message.reply_text(f"❌ Failed to remove premium.\n<code>{e}</code>")

@Client.on_message(
    filters.command("premium") & filters.private & filters.incoming & admin_only()
)
async def premium_stats_command(client: Client, message: Message):
    stats = await collect_stats()
    await message.reply_text(
        f"<b>💎 PREMIUM STATISTICS</b>\n\nACTIVE PREMIUM USERS: <code>{format_number(stats['premium'])}</code>",
        reply_markup=back_button("admin#home")
    )

@Client.on_message(
    filters.command("maintenance") & filters.private & filters.incoming & admin_only()
)
async def maintenance_command(client: Client, message: Message):
    if len(message.command) > 1:
        action = message.command[1].lower()
        if action == "on":
            await set_maintenance(client, message.from_user.id, True)
            await message.reply_text("🔧 MAINTENANCE MODE <b>ENABLED</b>.", reply_markup=back_button("admin#home"))
        elif action == "off":
            await set_maintenance(client, message.from_user.id, False)
            await message.reply_text("🔧 MAINTENANCE MODE <b>DISABLED</b>.", reply_markup=back_button("admin#home"))
        else:
            await message.reply_text("Usage: /maintenance [on|off]", reply_markup=back_button("admin#home"))
    else:
        await message.reply_text(
            "<b>🔧 MAINTENANCE MODE</b>\n\nToggle maintenance mode:\n/maintenance on\n/maintenance off",
            reply_markup=back_button("admin#home")
        )

async def set_maintenance(client, bot_id: int, enabled: bool):
    try:
        if db and hasattr(db, "update_maintenance_status"):
            await db.update_maintenance_status(bot_id, enabled)
            return True
    except Exception:
        logger.exception("Failed to update maintenance status")
    return False

@Client.on_message(
    filters.command("broadcast") & filters.private & filters.incoming & admin_only()
)
async def broadcast_command(client: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text(
            "📢 <b>BROADCAST</b>\n\nReply to the message you want to broadcast and use:\n<code>/broadcast</code>",
            reply_markup=back_button("admin#home")
        )
    admin_states[message.from_user.id] = {
        "action": "broadcast",
        "message_id": message.reply_to_message.id,
        "chat_id": message.reply_to_message.chat.id,
        "created_at": datetime.utcnow(),
    }
    await message.reply_text(
        "<b>📢 BROADCAST READY</b>\n\nChoose destination.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 USERS", callback_data="broadcast#users"),
             InlineKeyboardButton("👥 GROUPS", callback_data="broadcast#groups")],
            [InlineKeyboardButton("❌ CANCEL", callback_data="broadcast#cancel")],
        ])
    )

# ----------------------------------------------------------------------------
# Broadcast callback
# ----------------------------------------------------------------------------

@Client.on_callback_query(filters.regex(r"^broadcast#"))
async def broadcast_callback_handler(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await safe_answer(query, "⛔ Unauthorized.", show_alert=True)
        return
    action = query.data.split("#", 1)[1]
    if action == "cancel":
        admin_states.pop(query.from_user.id, None)
        await safe_answer(query, "Broadcast cancelled.")
        await safe_edit(query, "❌ BROADCAST CANCELLED.", main_dashboard_keyboard())
        return
    if action not in ("users", "groups"):
        await safe_answer(query, "Invalid target.", show_alert=True)
        return
    state = admin_states.get(query.from_user.id)
    if not state:
        await safe_answer(query, "Session expired. Start again with /broadcast.", show_alert=True)
        return
    await safe_answer(query, f"Starting {action} broadcast...")
    await safe_edit(query, f"<b>📢 BROADCAST STARTED</b>\n\nTARGET: <code>{action}</code>\n\nProcessing...")
    # Here you would implement the actual broadcast logic using the saved message
    # For now, just a simulation
    await asyncio.sleep(2)
    await safe_edit(query, f"✅ BROADCAST TO {action.upper()} COMPLETED (simulated).", main_dashboard_keyboard())
    admin_states.pop(query.from_user.id, None)

# ----------------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------------

def register(app: Client):
    """Register all admin handlers and callbacks."""
    # Message handlers
    app.add_handler(MessageHandler(admin_panel, filters.command("admin") & filters.private & admin_only()))
    app.add_handler(MessageHandler(dashboard_command, filters.command("dashboard") & filters.private & admin_only()))
    app.add_handler(MessageHandler(stats_command, filters.command("stats") & filters.private & admin_only()))
    app.add_handler(MessageHandler(users_command, filters.command("users") & filters.private & admin_only()))
    app.add_handler(MessageHandler(groups_command, filters.command("groups") & filters.private & admin_only()))
    app.add_handler(MessageHandler(ban_command, filters.command("ban") & filters.private & admin_only()))
    app.add_handler(MessageHandler(unban_command, filters.command("unban") & filters.private & admin_only()))
    app.add_handler(MessageHandler(add_premium_command, filters.command("addpremium") & filters.private & admin_only()))
    app.add_handler(MessageHandler(del_premium_command, filters.command("delpremium") & filters.private & admin_only()))
    app.add_handler(MessageHandler(premium_stats_command, filters.command("premium") & filters.private & admin_only()))
    app.add_handler(MessageHandler(maintenance_command, filters.command("maintenance") & filters.private & admin_only()))
    app.add_handler(MessageHandler(broadcast_command, filters.command("broadcast") & filters.private & admin_only()))

    # Callback handlers
    # admin#... callbacks (dashboard, search, indexing, uploads, logs, health, users, groups, files, premium, maintenance, broadcast, settings, refresh, home, close)
    app.add_handler(CallbackQueryHandler(dashboard_callback, filters.regex(r"^admin#dashboard$")))
    app.add_handler(CallbackQueryHandler(dashboard_refresh, filters.regex(r"^admin#dashboard_refresh$")))
    app.add_handler(CallbackQueryHandler(search_analytics_callback, filters.regex(r"^admin#search$")))
    app.add_handler(CallbackQueryHandler(indexing_callback, filters.regex(r"^admin#indexing$")))
    app.add_handler(CallbackQueryHandler(rebuild_index_callback, filters.regex(r"^admin#index_rebuild$")))
    app.add_handler(CallbackQueryHandler(uploads_callback, filters.regex(r"^admin#uploads$")))
    app.add_handler(CallbackQueryHandler(logs_callback, filters.regex(r"^admin#logs$")))
    app.add_handler(CallbackQueryHandler(health_callback, filters.regex(r"^admin#health$")))
    app.add_handler(CallbackQueryHandler(users_callback, filters.regex(r"^admin#users$")))
    app.add_handler(CallbackQueryHandler(users_page_callback, filters.regex(r"^admin#users_page:")))
    app.add_handler(CallbackQueryHandler(groups_callback, filters.regex(r"^admin#groups$")))
    app.add_handler(CallbackQueryHandler(groups_page_callback, filters.regex(r"^admin#groups_page:")))
    app.add_handler(CallbackQueryHandler(files_callback, filters.regex(r"^admin#files$")))
    app.add_handler(CallbackQueryHandler(premium_callback, filters.regex(r"^admin#premium$")))
    app.add_handler(CallbackQueryHandler(maintenance_callback, filters.regex(r"^admin#maintenance$")))
    app.add_handler(CallbackQueryHandler(broadcast_callback, filters.regex(r"^admin#broadcast$")))
    app.add_handler(CallbackQueryHandler(settings_callback, filters.regex(r"^admin#settings$")))
    app.add_handler(CallbackQueryHandler(refresh_all_callback, filters.regex(r"^admin#refresh$")))
    app.add_handler(CallbackQueryHandler(home_callback, filters.regex(r"^admin#home$")))
    app.add_handler(CallbackQueryHandler(close_callback, filters.regex(r"^admin#close$")))

    # Broadcast callbacks
    app.add_handler(CallbackQueryHandler(broadcast_callback_handler, filters.regex(r"^broadcast#")))

    logger.info("Ultimate admin handlers registered (CAPS buttons).")

# ----------------------------------------------------------------------------
# Exports
# ----------------------------------------------------------------------------

__all__ = [
    "register",
    "admin_panel",
    "dashboard_command",
    "log_operation",
]
