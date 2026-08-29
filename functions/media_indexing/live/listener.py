"""
Live Channel Upload Event Handler.
"""

from __future__ import annotations

import time
from pyrogram import Client, filters
from pyrogram.types import Message
from functions.media_indexing.database.manager import DatabaseManager
from functions.media_indexing.duplicate.policy import DuplicatePolicy
from functions.media_indexing.metadata.parser import MetadataParser
from app.logging import get_logger

LOGGER = get_logger(__name__)


def setup_live_indexing(client: Client, db_manager: DatabaseManager, channel_ids: list[int]) -> None:
    if not channel_ids:
        LOGGER.info("No live DATABASE_CHANNELS specified. Live indexing listener inactive.")
        return

    duplicate_policy = DuplicatePolicy(db_manager)

    @client.on_message(filters.chat(channel_ids) & (filters.document | filters.video | filters.audio))
    async def handle_live_media(_, message: Message) -> None:
        media = message.document or message.video or message.audio
        if not media:
            return

        file_name = getattr(media, "file_name", "") or "media_file"
        caption = message.caption or ""

        meta = MetadataParser.parse(file_name, caption)
        is_dup, reason = await duplicate_policy.is_duplicate(media.file_unique_id, meta, media.file_size)

        if is_dup:
            LOGGER.info("LIVE INDEX 🟡 DUPLICATE (%s) → SKIPPED | %s", reason, file_name)
            return

        active_db, db_name = await db_manager.check_and_rotate()
        doc = {
            "file_id": media.file_id,
            "file_unique_id": media.file_unique_id,
            "file_size": media.file_size,
            "original_name": meta.original_name,
            "clean_name": meta.clean_name,
            "title": meta.title,
            "normalized_title": meta.normalized_title,
            "year": meta.year,
            "resolution": meta.resolution,
            "quality": meta.quality,
            "codec": meta.codec,
            "languages": meta.languages,
            "season": meta.season,
            "episode": meta.episode,
            "is_series": meta.is_series,
            "source_chat_id": message.chat.id,
            "source_message_id": message.id,
            "caption": caption,
            "created_at": time.time(),
        }

        await active_db.media.insert_one(doc)
        LOGGER.info("LIVE INDEX 🟩 NEW → %s | %s", db_name, file_name)
