"""DOWNTOWN VILLA Media Indexing registration and commands."""
from __future__ import annotations
import asyncio
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from .config import load_config
from .models import IndexMode, IndexStats
from .pipeline import MediaProcessor
from .historical.scanner import scan_backward
from .historical.job import HistoricalJob


def _mode_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 MOVIES", callback_data="dvmi:movies"),
            InlineKeyboardButton("📺 SERIES", callback_data="dvmi:series"),
        ],
        [InlineKeyboardButton("🎬📺 BOTH", callback_data="dvmi:both")],
    ])


def register(runtime) -> None:
    config = load_config()
    logger = getattr(runtime, "logger", None)
    processor = MediaProcessor(logger=logger)
    jobs: dict[int, HistoricalJob] = {}

    @runtime.client.on_message(filters.command("index") & filters.reply)
    async def index_command(client, message: Message):
        if not config.historical_enabled:
            await message.reply_text("🏙️ DOWNTOWN VILLA: historical indexing is disabled.")
            return

        source = message.reply_to_message
        if not source:
            await message.reply_text("🏙️ Reply to the starting channel message with /index.")
            return

        await message.reply_text(
            "🏙️ <b>DOWNTOWN VILLA — HISTORICAL INDEXING</b>\n\n"
            "Starting from the replied message and moving toward older messages.\n\n"
            "Choose the indexing mode:",
            reply_markup=_mode_keyboard(),
        )

    @runtime.client.on_callback_query(filters.regex(r"^dvmi:(movies|series|both)$"))
    async def mode_callback(client, query):
        mode = IndexMode(query.data.rsplit(":", 1)[1])
        source = query.message.reply_to_message

        if source is None:
            await query.answer("Reply to the starting message first.", show_alert=True)
            return

        job = HistoricalJob(
            chat_id=int(source.chat.id),
            start_message_id=int(source.id),
            mode=mode,
        )
        owner_id = int(query.from_user.id)
        old = jobs.get(owner_id)
        if old and not old.cancelled:
            await query.answer("An indexing job is already running.", show_alert=True)
            return

        jobs[owner_id] = job
        await query.answer("Indexing started.")

        await query.message.edit_text(
            "🏙️ <b>DOWNTOWN VILLA — INDEXING STARTED</b>\n\n"
            f"Mode: <b>{mode.value.upper()}</b>\n"
            f"Start message: <code>{source.id}</code>\n\n"
            "🔄 Scanning backward...\n"
            "🧠 Metadata extraction active\n"
            "🚫 Duplicate protection active"
        )

        # The database repository is intentionally injected by the application's
        # MongoDB integration. This first handler safely performs the scan and
        # classification even before a repository is configured.
        async def run():
            try:
                async for item in scan_backward(
                    client,
                    job.chat_id,
                    job.start_message_id,
                    limit=config.max_scan_messages,
                ):
                    if job.cancelled:
                        break
                    await processor.process_message(item, mode, job.stats)
                    if job.stats.scanned % config.progress_every == 0:
                        if logger:
                            logger.info(
                                "INDEX PROGRESS | scanned=%s saved=%s duplicates=%s filtered=%s errors=%s",
                                job.stats.scanned,
                                job.stats.saved,
                                job.stats.duplicates,
                                job.stats.filtered,
                                job.stats.errors,
                            )
            except Exception:
                job.stats.errors += 1
                if logger:
                    logger.exception("Historical indexing job failed")
            finally:
                if logger:
                    logger.info(
                        "INDEX COMPLETE | scanned=%s saved=%s duplicates=%s filtered=%s errors=%s",
                        job.stats.scanned,
                        job.stats.saved,
                        job.stats.duplicates,
                        job.stats.filtered,
                        job.stats.errors,
                    )
                jobs.pop(owner_id, None)

        asyncio.create_task(run())

    if config.live_enabled and config.database_channels:
        from .live.listener import register_live_listener
        register_live_listener(runtime, processor, config.database_channels)

    if logger:
        logger.info(
            "DOWNTOWN VILLA media indexing loaded | live_channels=%s",
            config.database_channels,
        )
