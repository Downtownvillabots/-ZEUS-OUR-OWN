"""
Feature Entrypoint for Media Indexing System.
"""

from __future__ import annotations

import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.runtime import Runtime
from functions.media_indexing.config import MediaIndexingConfig
from functions.media_indexing.database.manager import DatabaseManager
from functions.media_indexing.historical.job import HistoricalIndexer
from functions.media_indexing.live.listener import setup_live_indexing
from app.logging import get_logger

LOGGER = get_logger(__name__)


def register_media_indexing(runtime: Runtime) -> None:
    config = MediaIndexingConfig.from_env()
    db_manager = DatabaseManager(
        core_uri=config.core_db_uri,
        media_uris=config.media_db_uris,
        rotation_mb=config.rotation_mb,
    )

    runtime.add_task(asyncio.create_task(db_manager.connect()))
    setup_live_indexing(runtime.client, db_manager, config.database_channels)

    @runtime.client.on_message(filters.command("index") & filters.reply)
    async def cmd_index(client: Client, message: Message) -> None:
        target_msg = message.reply_to_message
        if not target_msg or not target_msg.forward_from_chat:
            await message.reply_text("❌ Reply to a **forwarded channel message** to set starting position.")
            return

        chat_id = target_msg.forward_from_chat.id
        start_msg_id = target_msg.forward_from_message_id

        buttons = [
            [
                InlineKeyboardButton("🎬 MOVIES", callback_data=f"idx_m|{chat_id}|{start_msg_id}"),
                InlineKeyboardButton("📺 SERIES", callback_data=f"idx_s|{chat_id}|{start_msg_id}"),
            ],
            [
                InlineKeyboardButton("🎬📺 BOTH", callback_data=f"idx_b|{chat_id}|{start_msg_id}"),
            ]
        ]

        await message.reply_text(
            "🏙️ **DOWNTOWN VILLA — HISTORICAL INDEXING**\n\nChoose indexing mode:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    @runtime.client.on_callback_query(filters.regex(r"^idx_(m|s|b)\|"))
    async def cb_mode_select(client: Client, query: CallbackQuery) -> None:
        parts = query.data.split("|")
        mode_code = parts[0]
        chat_id = int(parts[1])
        start_msg_id = int(parts[2])

        mode = {"idx_m": "MOVIES", "idx_s": "SERIES", "idx_b": "BOTH"}[mode_code]

        status_msg = await query.message.edit_text(
            f"🏙️ **DOWNTOWN VILLA — INDEXER**\n\nInitializing scan in **{mode}** mode..."
        )

        indexer = HistoricalIndexer(client, db_manager)
        task = asyncio.create_task(indexer.run(status_msg, chat_id, start_msg_id, mode))
        runtime.add_task(task)
