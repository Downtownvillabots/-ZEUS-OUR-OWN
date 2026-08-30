"""
Telegram channel indexing service.

Responsibilities:
- Read Telegram messages in bounded batches.
- Extract supported media.
- Convert media to FileRecord objects.
- Persist through FileRepository.
- Track progress, duplicates, deleted/non-media/unsupported messages and errors.
- Support cooperative cancellation.
- Avoid loading an entire channel into memory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from math import ceil
from typing import Any, Awaitable, Callable, Optional

from pyrogram import Client, enums
from pyrogram.types import Message

from .files import (
    FileRecord,
    FileRepository,
    SAVE_DUPLICATE,
    SAVE_ERROR,
    SAVE_OK,
    record_from_pyrogram_message,
)

logger = logging.getLogger(__name__)


ProgressCallback = Callable[["IndexProgress"], Awaitable[None] | None]


@dataclass(slots=True)
class IndexProgress:
    chat_id: int | str
    start_message_id: int
    end_message_id: int
    current_message_id: int

    total_messages: int
    processed_messages: int

    saved: int = 0
    duplicates: int = 0
    deleted: int = 0
    non_media: int = 0
    unsupported: int = 0
    errors: int = 0
    batches_completed: int = 0
    total_batches: int = 0

    elapsed_seconds: float = 0.0
    eta_seconds: float = 0.0

    cancelled: bool = False

    @property
    def percentage(self) -> float:
        if self.total_messages <= 0:
            return 100.0
        return min(
            100.0,
            max(0.0, self.processed_messages / self.total_messages * 100),
        )


@dataclass(slots=True)
class IndexResult:
    chat_id: int | str
    requested_start: int
    requested_end: int
    processed_messages: int

    saved: int
    duplicates: int
    deleted: int
    non_media: int
    unsupported: int
    errors: int

    elapsed_seconds: float
    cancelled: bool = False

    @property
    def total_files_seen(self) -> int:
        return self.saved + self.duplicates


class IndexCancelled(Exception):
    """Raised internally when indexing is cooperatively cancelled."""


class Indexer:
    """
    Service object responsible for channel indexing.

    The service deliberately knows about Pyrogram messages but does not know
    about Telegram UI, callback queries or bot command handlers. UI handlers
    should call index() and use the progress callback.
    """

    def __init__(
        self,
        bot: Client,
        repository: FileRepository,
        *,
        batch_size: int = 200,
        concurrency: int = 25,
    ) -> None:
        self.bot = bot
        self.repository = repository

        self.batch_size = max(1, min(int(batch_size), 200))
        self.concurrency = max(1, int(concurrency))

        self._cancel_events: dict[str, asyncio.Event] = {}
        self._cancel_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    @staticmethod
    def _job_key(chat_id: int | str, end_message_id: int) -> str:
        return f"{chat_id}:{end_message_id}"

    async def _get_cancel_event(
        self,
        chat_id: int | str,
        end_message_id: int,
    ) -> asyncio.Event:
        key = self._job_key(chat_id, end_message_id)

        async with self._cancel_lock:
            event = self._cancel_events.get(key)
            if event is None:
                event = asyncio.Event()
                self._cancel_events[key] = event
            return event

    async def cancel(
        self,
        chat_id: int | str,
        end_message_id: int,
    ) -> bool:
        """Request cancellation of an active indexing job."""
        key = self._job_key(chat_id, end_message_id)

        async with self._cancel_lock:
            event = self._cancel_events.get(key)
            if event is None:
                return False
            event.set()
            return True

    async def _remove_cancel_event(
        self,
        chat_id: int | str,
        end_message_id: int,
    ) -> None:
        key = self._job_key(chat_id, end_message_id)

        async with self._cancel_lock:
            self._cancel_events.pop(key, None)

    # ------------------------------------------------------------------
    # Public indexing API
    # ------------------------------------------------------------------

    async def index(
        self,
        chat_id: int | str,
        end_message_id: int,
        *,
        start_message_id: int = 1,
        progress_callback: Optional[ProgressCallback] = None,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> IndexResult:
        """
        Index message IDs from start_message_id through end_message_id.

        Telegram message IDs are sparse in real channels, so a requested ID
        can correspond to an empty/deleted message. Such messages are counted
        as deleted and do not stop the indexing job.
        """
        start_message_id = max(1, int(start_message_id))
        end_message_id = int(end_message_id)

        if end_message_id < start_message_id:
            return IndexResult(
                chat_id=chat_id,
                requested_start=start_message_id,
                requested_end=end_message_id,
                processed_messages=0,
                saved=0,
                duplicates=0,
                deleted=0,
                non_media=0,
                unsupported=0,
                errors=0,
                elapsed_seconds=0.0,
            )

        total_messages = end_message_id - start_message_id + 1
        total_batches = ceil(total_messages / self.batch_size)

        cancel_event = cancellation_event or await self._get_cancel_event(
            chat_id,
            end_message_id,
        )

        progress = IndexProgress(
            chat_id=chat_id,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            current_message_id=start_message_id - 1,
            total_messages=total_messages,
            processed_messages=0,
            total_batches=total_batches,
        )

        started = time.monotonic()

        try:
            await self._emit_progress(progress, progress_callback)

            for batch_number in range(total_batches):
                self._raise_if_cancelled(cancel_event)

                batch_start = (
                    start_message_id + batch_number * self.batch_size
                )
                batch_end = min(
                    end_message_id,
                    batch_start + self.batch_size - 1,
                )

                batch_started = time.monotonic()

                await self._process_batch(
                    chat_id,
                    batch_start,
                    batch_end,
                    progress,
                    cancel_event,
                )

                progress.batches_completed = batch_number + 1
                progress.current_message_id = batch_end
                progress.processed_messages = (
                    batch_end - start_message_id + 1
                )

                progress.elapsed_seconds = time.monotonic() - started

                remaining = max(
                    0,
                    total_messages - progress.processed_messages,
                )

                batch_elapsed = max(
                    0.001,
                    time.monotonic() - batch_started,
                )

                # ETA is estimated using messages/sec from the latest batch.
                messages_per_second = (
                    (batch_end - batch_start + 1) / batch_elapsed
                )
                progress.eta_seconds = (
                    remaining / messages_per_second
                    if messages_per_second > 0
                    else 0
                )

                await self._emit_progress(progress, progress_callback)

            progress.elapsed_seconds = time.monotonic() - started
            progress.eta_seconds = 0

            return self._result_from_progress(progress)

        except IndexCancelled:
            progress.cancelled = True
            progress.elapsed_seconds = time.monotonic() - started
            await self._emit_progress(progress, progress_callback)
            return self._result_from_progress(progress)

        finally:
            if cancellation_event is None:
                await self._remove_cancel_event(
                    chat_id,
                    end_message_id,
                )

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    async def _process_batch(
        self,
        chat_id: int | str,
        start_id: int,
        end_id: int,
        progress: IndexProgress,
        cancel_event: asyncio.Event,
    ) -> None:
        message_ids = list(range(start_id, end_id + 1))

        try:
            messages = await self.bot.get_messages(
                chat_id,
                message_ids,
            )

            if not isinstance(messages, list):
                messages = [messages]

        except Exception as exc:
            logger.exception(
                "Failed fetching messages %s-%s from %s",
                start_id,
                end_id,
                chat_id,
            )
            progress.errors += len(message_ids)
            return

        # get_messages(list) can return results in ID order, but we do not
        # depend on that. Missing IDs are accounted for below.
        message_map: dict[int, Message] = {}

        for message in messages:
            if message is None:
                continue

            message_id = getattr(message, "id", None)
            if message_id is not None:
                message_map[int(message_id)] = message

        # Messages returned by Telegram may be fewer than requested because
        # some IDs are deleted/nonexistent.
        missing_count = len(message_ids) - len(message_map)
        if missing_count > 0:
            progress.deleted += missing_count

        records: list[FileRecord] = []

        for message_id in message_ids:
            self._raise_if_cancelled(cancel_event)

            message = message_map.get(message_id)

            if message is None:
                continue

            if getattr(message, "empty", False):
                progress.deleted += 1
                continue

            if not getattr(message, "media", None):
                progress.non_media += 1
                continue

            record = record_from_pyrogram_message(message)

            if record is None:
                progress.unsupported += 1
                continue

            records.append(record)

        if not records:
            return

        # Bulk insertion is substantially faster than one DB operation per
        # Telegram message and still returns duplicate/error counts.
        result = await self.repository.bulk_insert(records)

        progress.saved += result["saved"]
        progress.duplicates += result["duplicates"]
        progress.errors += result["errors"]

    # ------------------------------------------------------------------
    # Alternative concurrent mode
    # ------------------------------------------------------------------

    async def index_stream(
        self,
        chat_id: int | str,
        end_message_id: int,
        *,
        start_message_id: int = 1,
        progress_callback: Optional[ProgressCallback] = None,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> IndexResult:
        """
        Streaming variant using individual get_messages calls with bounded
        concurrency.

        Use index() by default. This variant can be useful when Telegram
        behaves poorly with large ID-list requests.
        """
        start_message_id = max(1, int(start_message_id))
        end_message_id = int(end_message_id)

        if end_message_id < start_message_id:
            return IndexResult(
                chat_id=chat_id,
                requested_start=start_message_id,
                requested_end=end_message_id,
                processed_messages=0,
                saved=0,
                duplicates=0,
                deleted=0,
                non_media=0,
                unsupported=0,
                errors=0,
                elapsed_seconds=0,
            )

        total = end_message_id - start_message_id + 1
        cancel_event = cancellation_event or await self._get_cancel_event(
            chat_id,
            end_message_id,
        )

        progress = IndexProgress(
            chat_id=chat_id,
            start_message_id=start_message_id,
            end_message_id=end_message_id,
            current_message_id=start_message_id - 1,
            total_messages=total,
            processed_messages=0,
            total_batches=ceil(total / self.batch_size),
        )

        semaphore = asyncio.Semaphore(self.concurrency)
        started = time.monotonic()

        async def process_one(message_id: int) -> None:
            async with semaphore:
                self._raise_if_cancelled(cancel_event)

                try:
                    message = await self.bot.get_messages(
                        chat_id,
                        message_id,
                    )
                except Exception:
                    progress.errors += 1
                    return

                if not message or getattr(message, "empty", False):
                    progress.deleted += 1
                    return

                if not getattr(message, "media", None):
                    progress.non_media += 1
                    return

                record = record_from_pyrogram_message(message)

                if record is None:
                    progress.unsupported += 1
                    return

                ok, code = await self.repository.insert(record)

                if ok and code == SAVE_OK:
                    progress.saved += 1
                elif code == SAVE_DUPLICATE:
                    progress.duplicates += 1
                else:
                    progress.errors += 1

        try:
            await self._emit_progress(progress, progress_callback)

            for batch_start in range(
                start_message_id,
                end_message_id + 1,
                self.batch_size,
            ):
                self._raise_if_cancelled(cancel_event)

                batch_end = min(
                    end_message_id,
                    batch_start + self.batch_size - 1,
                )

                tasks = [
                    asyncio.create_task(process_one(message_id))
                    for message_id in range(batch_start, batch_end + 1)
                ]

                await asyncio.gather(*tasks)

                progress.processed_messages = (
                    batch_end - start_message_id + 1
                )
                progress.current_message_id = batch_end
                progress.batches_completed += 1
                progress.elapsed_seconds = time.monotonic() - started

                processed = max(1, progress.processed_messages)
                rate = processed / max(progress.elapsed_seconds, 0.001)
                remaining = max(0, total - processed)
                progress.eta_seconds = remaining / rate

                await self._emit_progress(progress, progress_callback)

            progress.eta_seconds = 0
            return self._result_from_progress(progress)

        except IndexCancelled:
            progress.cancelled = True
            progress.elapsed_seconds = time.monotonic() - started
            await self._emit_progress(progress, progress_callback)
            return self._result_from_progress(progress)

        finally:
            if cancellation_event is None:
                await self._remove_cancel_event(
                    chat_id,
                    end_message_id,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_if_cancelled(event: asyncio.Event) -> None:
        if event.is_set():
            raise IndexCancelled()

    @staticmethod
    async def _emit_progress(
        progress: IndexProgress,
        callback: Optional[ProgressCallback],
    ) -> None:
        if callback is None:
            return

        result = callback(progress)

        if asyncio.iscoroutine(result):
            await result

    @staticmethod
    def _result_from_progress(
        progress: IndexProgress,
    ) -> IndexResult:
        return IndexResult(
            chat_id=progress.chat_id,
            requested_start=progress.start_message_id,
            requested_end=progress.end_message_id,
            processed_messages=progress.processed_messages,
            saved=progress.saved,
            duplicates=progress.duplicates,
            deleted=progress.deleted,
            non_media=progress.non_media,
            unsupported=progress.unsupported,
            errors=progress.errors,
            elapsed_seconds=progress.elapsed_seconds,
            cancelled=progress.cancelled,
        )


# ----------------------------------------------------------------------
# Compatibility facade for the old bot
# ----------------------------------------------------------------------

_indexer_instances: dict[int, Indexer] = {}


def get_indexer(
    bot: Client,
    repository: FileRepository,
    *,
    batch_size: int = 200,
    concurrency: int = 25,
) -> Indexer:
    """
    Return one Indexer per Pyrogram client.

    This prevents accidentally creating many cancellation registries for the
    same bot instance.
    """
    key = id(bot)

    instance = _indexer_instances.get(key)

    if instance is None or instance.repository is not repository:
        instance = Indexer(
            bot,
            repository,
            batch_size=batch_size,
            concurrency=concurrency,
        )
        _indexer_instances[key] = instance

    return instance


async def index_files_to_db(
    bot: Client,
    repository: FileRepository,
    lst_msg_id: int,
    chat: int | str,
    *,
    start_message_id: int = 1,
    progress_callback: Optional[ProgressCallback] = None,
    cancellation_event: Optional[asyncio.Event] = None,
    batch_size: int = 200,
) -> IndexResult:
    """
    Drop-in style function replacing the old index_files_to_db() service.

    UI handlers can use this without knowing the Indexer class.
    """
    indexer = get_indexer(
        bot,
        repository,
        batch_size=batch_size,
    )

    return await indexer.index(
        chat,
        int(lst_msg_id),
        start_message_id=start_message_id,
        progress_callback=progress_callback,
        cancellation_event=cancellation_event,
    )


def format_progress(progress: IndexProgress) -> str:
    """Telegram-friendly progress text."""
    percent = progress.percentage

    filled = int(percent // 10)
    filled = max(0, min(10, filled))

    bar = "🟩" * filled + "⬜️" * (10 - filled)

    return (
        f"📊 <b>Indexing Progress</b>\n"
        f"{bar} <code>{percent:.1f}%</code>\n\n"
        f"💬 Total Messages: <code>{progress.total_messages}</code>\n"
        f"📥 Processed: <code>{progress.processed_messages}</code>\n"
        f"💾 Saved: <code>{progress.saved}</code>\n"
        f"♻️ Duplicates: <code>{progress.duplicates}</code>\n"
        f"🗑 Deleted: <code>{progress.deleted}</code>\n"
        f"📝 Non-Media: <code>{progress.non_media}</code>\n"
        f"🚫 Unsupported: <code>{progress.unsupported}</code>\n"
        f"⚠️ Errors: <code>{progress.errors}</code>\n"
        f"⏱️ Elapsed: <code>{format_duration(progress.elapsed_seconds)}</code>\n"
        f"⏰ ETA: <code>{format_duration(progress.eta_seconds)}</code>"
    )


def format_result(result: IndexResult) -> str:
    """Telegram-friendly final indexing summary."""
    status = "🛑 Indexing Cancelled" if result.cancelled else "✅ Indexing Completed"

    return (
        f"<b>{status}</b>\n\n"
        f"💬 Processed: <code>{result.processed_messages}</code>\n"
        f"💾 Saved: <code>{result.saved}</code>\n"
        f"♻️ Duplicates: <code>{result.duplicates}</code>\n"
        f"🗑 Deleted: <code>{result.deleted}</code>\n"
        f"📝 Non-Media: <code>{result.non_media}</code>\n"
        f"🚫 Unsupported: <code>{result.unsupported}</code>\n"
        f"⚠️ Errors: <code>{result.errors}</code>\n"
        f"⏱️ Elapsed: <code>{format_duration(result.elapsed_seconds)}</code>"
    )


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


__all__ = [
    "Indexer",
    "IndexProgress",
    "IndexResult",
    "IndexCancelled",
    "get_indexer",
    "index_files_to_db",
    "format_progress",
    "format_result",
    "format_duration",
]
