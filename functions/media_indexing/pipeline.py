"""Single processing pipeline shared by historical and live indexing."""
from __future__ import annotations
from .models import IndexMode, IndexStats
from .metadata.parser import parse
from .duplicate.policy import is_duplicate


def classify(parsed, mode: IndexMode) -> bool:
    if mode is IndexMode.MOVIES:
        return not parsed.is_series
    if mode is IndexMode.SERIES:
        return parsed.is_series
    return True


class MediaProcessor:
    def __init__(self, repository=None, logger=None):
        self.repository = repository
        self.logger = logger

    @staticmethod
    def media_object(message):
        return (
            getattr(message, "document", None)
            or getattr(message, "video", None)
            or getattr(message, "audio", None)
        )

    async def process_message(self, message, mode: IndexMode = IndexMode.BOTH, stats: IndexStats | None = None):
        stats = stats or IndexStats()
        stats.scanned += 1

        media = self.media_object(message)
        if media is None:
            stats.unsupported += 1
            return "unsupported"

        filename = getattr(media, "file_name", None) or ""
        if not filename:
            filename = "unknown"

        parsed = parse(filename, getattr(message, "caption", None))
        if not classify(parsed, mode):
            stats.filtered += 1
            if self.logger:
                self.logger.info(
                    "INDEX SKIPPED | mode=%s | file=%s",
                    mode.value,
                    filename,
                )
            return "filtered"

        stats.accepted += 1
        file_size = int(getattr(media, "file_size", 0) or 0)
        file_id = str(getattr(media, "file_id", "") or "")
        unique_id = getattr(media, "file_unique_id", None)

        if not file_id:
            stats.errors += 1
            return "error"

        if self.repository is not None:
            if await self.repository.duplicate_exists(
                parsed,
                file_size=file_size,
                file_unique_id=unique_id,
            ):
                stats.duplicates += 1
                if self.logger:
                    self.logger.info(
                        "INDEX SKIPPED DUPLICATE | %s | %s bytes | already in database",
                        parsed.title,
                        file_size,
                    )
                return "duplicate"

            record = {
                "file_id": file_id,
                "file_unique_id": unique_id,
                "file_size": file_size,
                "media_type": type(media).__name__.lower(),
                "original_name": parsed.original_name,
                "clean_name": parsed.clean_name,
                "title": parsed.title,
                "normalized_title": parsed.normalized_title,
                "year": parsed.year,
                "resolution": parsed.resolution,
                "quality": parsed.quality,
                "codec": parsed.codec,
                "languages": list(parsed.languages),
                "audio_languages": list(parsed.audio_languages),
                "subtitle_languages": list(parsed.subtitle_languages),
                "season": parsed.season,
                "episode": parsed.episode,
                "is_series": parsed.is_series,
                "caption": getattr(message, "caption", None),
                "source_chat_id": int(message.chat.id),
                "source_message_id": int(message.id),
            }
            database_number = await self.repository.insert(record)
            stats.saved += 1
            if self.logger:
                self.logger.info(
                    "INDEX SAVED | %s | database=%s",
                    parsed.title,
                    database_number,
                )
            return "saved"

        return "accepted"
