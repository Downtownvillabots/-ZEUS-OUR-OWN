"""Live listener for configured database/dump channels."""
from __future__ import annotations
from pyrogram import filters


def register_live_listener(runtime, processor, channel_ids: tuple[int, ...]) -> None:
    if not channel_ids:
        return

    @runtime.client.on_message(filters.chat(list(channel_ids)))
    async def _database_channel_message(client, message):
        if not getattr(message, "media", None):
            return
        result = await processor.process_message(message)
        runtime.logger.info(
            "DOWNTOWN VILLA live indexing: message=%s result=%s",
            getattr(message, "id", "?"),
            result,
        )
