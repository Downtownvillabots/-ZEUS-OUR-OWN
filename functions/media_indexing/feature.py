"""Telegram-facing entry point for the DOWNTOWN VILLA indexing feature."""
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from .models import IndexMode
from .pipeline import classify_filename


def register(runtime) -> None:
    @runtime.client.on_message(filters.command("index"))
    async def index_command(client, message: Message):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 MOVIES", callback_data="dv:index:movies"),
             InlineKeyboardButton("📺 SERIES", callback_data="dv:index:series")],
            [InlineKeyboardButton("🎬📺 BOTH", callback_data="dv:index:both")],
        ])
        await message.reply_text(
            "🏙️ <b>DOWNTOWN VILLA — MEDIA INDEXER</b>\n\n"
            "Choose what this indexing run should process:",
            reply_markup=keyboard,
        )

    @runtime.client.on_callback_query(filters.regex(r"^dv:index:(movies|series|both)$"))
    async def mode_callback(client, query: CallbackQuery):
        mode = IndexMode(query.data.rsplit(":", 1)[1])
        await query.answer(f"{mode.value.upper()} selected")
        await query.message.edit_text(
            f"🏙️ <b>DOWNTOWN VILLA INDEXING</b>\n\n"
            f"Mode: <b>{mode.value.upper()}</b>\n\n"
            "The classifier and metadata engine are ready.\n"
            "Database writing will be connected in the next stage.",
        )
