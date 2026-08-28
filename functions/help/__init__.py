"""
DOWNTOWN VILLA
/help feature.
"""

from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from app.runtime import Runtime


HELP_TEXT = (
    "🏙️ <b>DOWNTOWN VILLA</b> — Help\n\n"
    "/start — Start the bot\n"
    "/help — Show this help\n"
    "/ping — Test bot response\n\n"
    "More features will be added one by one."
)


def register(runtime: Runtime) -> None:
    @runtime.client.on_message(filters.command("help"))
    async def help_handler(client, message: Message) -> None:
        await message.reply_text(HELP_TEXT)
