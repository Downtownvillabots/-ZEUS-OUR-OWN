"""
DOWNTOWN VILLA
Runtime test feature.

This is the first infrastructure verification command.
"""

from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from app.logging import get_logger
from app.runtime import Runtime


LOGGER = get_logger(__name__)


def register(runtime: Runtime) -> None:
    @runtime.client.on_message(filters.command("ping"))
    async def ping_handler(client, message: Message) -> None:
        await message.reply_text("🏙️ DOWNTOWN VILLA • PONG!")
