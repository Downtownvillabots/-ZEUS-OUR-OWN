"""
DOWNTOWN VILLA
/start feature.

Only /start behavior belongs here. Future start buttons/callbacks can be
added inside this feature without touching unrelated modules.
"""

from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from app.runtime import Runtime


START_TEXT = (
    "🏙️ <b>DOWNTOWN VILLA</b>\n\n"
    "Welcome! The new bot is online.\n\n"
    "Use /help to see the currently available commands."
)


def register(runtime: Runtime) -> None:
    @runtime.client.on_message(filters.command("start"))
    async def start_handler(client, message: Message) -> None:
        await message.reply_text(START_TEXT)
