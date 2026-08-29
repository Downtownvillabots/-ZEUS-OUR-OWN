"""
Historical Backward Channel Scanner Task.
"""

from __future__ import annotations

import time
from pyrogram import Client
from pyrogram.types import Message
from functions.media_indexing.database.manager import DatabaseManager
from functions.media_indexing.duplicate.policy import DuplicatePolicy
from functions.media_indexing.metadata.parser import MetadataParser
from functions.media_indexing.monitoring.progress import ProgressMonitor
from app.logging import get_logger

LOGGER = get_logger(__name__)


class HistoricalIndexer:
    def __init__(self, client: Client, db_manager: DatabaseManager) -> None:
        self.client = client
        self.db_manager = db_manager
        self.duplicate_policy = DuplicatePolicy(db_manager)

    async def run(self, status_msg: Message, chat_id: int, start_msg_id: int, mode: str) -> None:
        scanned = added = duplicates = series_skipped = unsupported = errors = 0
        total = start_msg_id
        start_time = time.time()
        last_edit_time = 0.0

        current_id = start_msg_id
        while current_id > 0:
            try:
                msg = await self.client.get_messages(chat_id, current_id)
                scanned += 1

                if msg and not msg.empty and (msg.document or msg.video or msg.audio):
                    media = msg.document or msg.video or msg.audio
                    file_name = getattr(media, "file_name", "") or "media_file"
                    caption = msg.caption or ""

                    meta = MetadataParser.parse(file_name, caption)

                    if mode == "MOVIES" and meta.is_series:
                        series_skipped += 1
                        LOGGER.info("📁 %d | %s 🔵 SERIES → SKIPPED (MOVIE MODE)", current_id, file_name)
                    elif mode == "SERIES" and not meta.is_series:
                        unsupported += 1
                        LOGGER.info("📁 %d | %s ⚪ MOVIE → SKIPPED (SERIES MODE)", current_id, file_name)
                    else:
                        is_dup, reason = await self.duplicate_policy.is_duplicate(media.file_unique_id, meta, media.file_size)
                        if is_dup:
                            duplicates += 1
                            LOGGER.info("📁 %d | %s 🟡 DUPLICATE (%s) → SKIPPED", current_id, file_name, reason)
                        else:
                            active_db, db_name = await self.db_manager.check_and_rotate()
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
                                "source_chat_id": chat_id,
                                "source_message_id": current_id,
                                "caption": caption,
                                "created_at": time.time(),
                            }
                            await active_db.media.insert_one(doc)
                            added += 1
                            LOGGER.info("📁 %d | %s 🟩 NEW → %s", current_id, file_name, db_name)
                else:
                    unsupported += 1
            except Exception as exc:
                errors += 1
                LOGGER.error("Error indexing message %d: %s", current_id, exc)

            now = time.time()
            if now - last_edit_time >= 3.0:
                last_edit_time = now
                db_obj, db_name = await self.db_manager.get_active_media_db()
                usage_bytes = await self.db_manager.get_db_usage_bytes(db_obj)
                text = ProgressMonitor.format_status(
                    mode=mode, scanned=scanned, total=total, added=added, duplicates=duplicates,
                    series_skipped=series_skipped, unsupported=unsupported, errors=errors,
                    start_time=start_time, active_db=db_name,
                    db_usage_mb=usage_bytes / (1024 * 1024),
                    target_mb=self.db_manager.rotation_bytes / (1024 * 1024),
                )
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass

            current_id -= 1

        db_obj, db_name = await self.db_manager.get_active_media_db()
        usage_bytes = await self.db_manager.get_db_usage_bytes(db_obj)
        final_text = ProgressMonitor.format_status(
            mode=mode, scanned=scanned, total=total, added=added, duplicates=duplicates,
            series_skipped=series_skipped, unsupported=unsupported, errors=errors,
            start_time=start_time, active_db=db_name,
            db_usage_mb=usage_bytes / (1024 * 1024),
            target_mb=self.db_manager.rotation_bytes / (1024 * 1024)
        ) + "\n\n✅ **INDEXING COMPLETE**"
        try:
            await status_msg.edit_text(final_text)
        except Exception:
            pass
