"""
bot/handlers/broadcast.py

Production-oriented administrator broadcast handler.

Features
--------
- /broadcast
- Broadcast a replied-to Telegram message
- Text broadcast
- Media/document broadcast through copy_message
- User broadcast
- Group broadcast
- Batch processing
- FloodWait handling
- Retry handling
- Progress updates
- Cancellation
- Admin-only access
- Broadcast state tracking
- Completion statistics
- Automatic cleanup

Expected architecture
---------------------
client.db
    Database/repository layer.

client.state_manager
    Optional state manager.

bot.handlers.admin
    Administrator authorization.

This module deliberately keeps database access behind small adapters so
the database implementation can evolve independently.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    PeerIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_BATCH_SIZE = 20

DEFAULT_BATCH_DELAY = 1.0

DEFAULT_MAX_RETRIES = 3

DEFAULT_PROGRESS_INTERVAL = 5

DEFAULT_FLOODWAIT_RETRIES = 5

MAX_BROADCAST_RECIPIENTS = 250_000


# ============================================================================
# Broadcast states
# ============================================================================

STATE_KEY_PREFIX = "broadcast:"


BROADCAST_STATE_IDLE = "idle"

BROADCAST_STATE_RUNNING = "running"

BROADCAST_STATE_CANCELLED = "cancelled"

BROADCAST_STATE_COMPLETED = "completed"

BROADCAST_STATE_FAILED = "failed"


# ============================================================================
# Data models
# ============================================================================

@dataclass
class BroadcastStats:
    """
    Runtime broadcast statistics.
    """

    total: int = 0

    processed: int = 0

    success: int = 0

    failed: int = 0

    blocked: int = 0

    deleted: int = 0

    invalid: int = 0

    flood_waits: int = 0

    retries: int = 0

    started_at: float = field(
        default_factory=time.monotonic
    )

    finished_at: Optional[float] = None

    last_error: Optional[str] = None

    def finish(self):
        self.finished_at = time.monotonic()

    @property
    def elapsed(self) -> float:
        end = (
            self.finished_at
            if self.finished_at is not None
            else time.monotonic()
        )

        return max(
            0.0,
            end - self.started_at,
        )

    @property
    def percentage(self) -> float:
        if self.total <= 0:
            return 100.0

        return min(
            100.0,
            (
                self.processed
                / self.total
            )
            * 100.0,
        )

    @property
    def rate(self) -> float:
        elapsed = self.elapsed

        if elapsed <= 0:
            return 0.0

        return (
            self.processed
            / elapsed
        )

    @property
    def remaining(self) -> int:
        return max(
            0,
            self.total
            - self.processed,
        )


@dataclass
class BroadcastJob:
    """
    Runtime broadcast job.
    """

    job_id: str

    admin_id: int

    source_chat_id: int

    source_message_id: int

    target_type: str = "users"

    batch_size: int = DEFAULT_BATCH_SIZE

    batch_delay: float = DEFAULT_BATCH_DELAY

    max_retries: int = DEFAULT_MAX_RETRIES

    progress_interval: int = DEFAULT_PROGRESS_INTERVAL

    created_at: float = field(
        default_factory=time.time
    )

    stats: BroadcastStats = field(
        default_factory=BroadcastStats
    )

    cancelled: bool = False

    running: bool = False

    status: str = BROADCAST_STATE_IDLE

    progress_message_chat_id: Optional[int] = None

    progress_message_id: Optional[int] = None

    task: Optional[asyncio.Task] = None

    recipients: list[int] = field(
        default_factory=list
    )

    lock: asyncio.Lock = field(
        default_factory=asyncio.Lock
    )

    def cancel(self):
        self.cancelled = True
        self.status = (
            BROADCAST_STATE_CANCELLED
        )

    def is_cancelled(self) -> bool:
        return self.cancelled


# ============================================================================
# Runtime registry
# ============================================================================

ACTIVE_BROADCASTS: dict[
    str,
    BroadcastJob,
] = {}


ADMIN_BROADCAST_LOCKS: dict[
    int,
    asyncio.Lock,
] = {}


# ============================================================================
# Generic helpers
# ============================================================================

def escape_html(
    value: Any,
) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_number(
    value: Any,
) -> str:

    try:
        return f"{int(value):,}"
    except (
        TypeError,
        ValueError,
    ):
        return "0"


def format_duration(
    seconds: float,
) -> str:

    seconds = max(
        0,
        int(seconds),
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes, seconds = divmod(
        seconds,
        60,
    )

    if minutes < 60:
        return (
            f"{minutes}m "
            f"{seconds}s"
        )

    hours, minutes = divmod(
        minutes,
        60,
    )

    return (
        f"{hours}h "
        f"{minutes}m"
    )


def get_database(
    client: Client,
):
    return getattr(
        client,
        "db",
        None,
    )


def get_admin_lock(
    admin_id: int,
) -> asyncio.Lock:

    admin_id = int(
        admin_id
    )

    lock = ADMIN_BROADCAST_LOCKS.get(
        admin_id
    )

    if lock is None:

        lock = asyncio.Lock()

        ADMIN_BROADCAST_LOCKS[
            admin_id
        ] = lock

    return lock


# ============================================================================
# Administrator authorization
# ============================================================================

async def is_admin(
    client: Client,
    user_id: int,
) -> bool:

    try:

        from bot.handlers.admin import (
            is_admin as check_admin,
        )

        return await check_admin(
            client,
            int(user_id),
        )

    except Exception:
        logger.exception(
            "Unable to validate administrator"
        )

        return False


async def require_admin(
    client: Client,
    message: Message,
) -> bool:

    user = message.from_user

    if user is None:
        return False

    if await is_admin(
        client,
        user.id,
    ):
        return True

    await message.reply_text(
        "🚫 <b>Administrator access required.</b>"
    )

    return False


async def require_admin_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:

    user = callback_query.from_user

    if user is None:
        return False

    if await is_admin(
        client,
        user.id,
    ):
        return True

    await callback_query.answer(
        "🚫 Administrator access required.",
        show_alert=True,
    )

    return False


# ============================================================================
# Database method adapter
# ============================================================================

async def call_db_method(
    client: Client,
    names: tuple[str, ...],
    *args,
    **kwargs,
):
    """
    Call the first database method available.

    Returns:

        found, result
    """

    db = get_database(
        client
    )

    if db is None:
        return False, None

    for name in names:

        method = getattr(
            db,
            name,
            None,
        )

        if method is None:
            continue

        try:

            result = method(
                *args,
                **kwargs,
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            return True, result

        except Exception:

            logger.exception(
                "Database method failed: %s",
                name,
            )

            return True, None

    return False, None


# ============================================================================
# Recipient discovery
# ============================================================================

async def get_user_ids(
    client: Client,
) -> list[int]:
    """
    Retrieve user IDs.

    Preferred database APIs are used first.
    """

    found, result = await call_db_method(
        client,
        (
            "get_all_users",
            "get_all_user_ids",
            "all_user_ids",
            "broadcast_users",
        ),
    )

    if not found:
        return []

    return normalize_recipient_ids(
        result
    )


async def get_group_ids(
    client: Client,
) -> list[int]:
    """
    Retrieve group IDs.
    """

    found, result = await call_db_method(
        client,
        (
            "get_all_chats",
            "get_all_chat_ids",
            "all_chat_ids",
            "broadcast_chats",
        ),
    )

    if not found:
        return []

    return normalize_recipient_ids(
        result
    )


def normalize_recipient_ids(
    result: Any,
) -> list[int]:
    """
    Normalize database recipient output.
    """

    if result is None:
        return []

    if isinstance(
        result,
        dict,
    ):

        for key in (
            "users",
            "chats",
            "ids",
            "results",
            "data",
        ):

            if key in result:

                return normalize_recipient_ids(
                    result[key]
                )

        for key in (
            "id",
            "user_id",
            "chat_id",
        ):

            if key in result:

                try:
                    return [
                        int(
                            result[key]
                        )
                    ]
                except (
                    TypeError,
                    ValueError,
                ):
                    return []

    if isinstance(
        result,
        (str, int),
    ):

        try:
            return [
                int(
                    result
                )
            ]
        except (
            TypeError,
            ValueError,
        ):
            return []

    try:
        iterator = iter(
            result
        )
    except TypeError:
        return []

    ids = []

    for item in iterator:

        if isinstance(
            item,
            dict,
        ):

            value = (
                item.get("id")
                or item.get("user_id")
                or item.get("chat_id")
            )

        else:

            value = getattr(
                item,
                "id",
                item,
            )

        try:

            ids.append(
                int(value)
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

    return list(
        dict.fromkeys(
            ids
        )
    )


# ============================================================================
# Broadcast job IDs
# ============================================================================

def make_job_id(
    admin_id: int,
) -> str:

    return (
        f"{int(admin_id)}-"
        f"{int(time.time() * 1000)}"
    )


# ============================================================================
# State manager
# ============================================================================

async def save_broadcast_state(
    client: Client,
    job: BroadcastJob,
):
    """
    Persist lightweight runtime state through the optional state manager.
    """

    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is None:
        return

    setter = getattr(
        state_manager,
        "set",
        None,
    )

    if setter is None:
        return

    payload = {
        "state": job.status,
        "job_id": job.job_id,
        "admin_id": job.admin_id,
        "target_type": job.target_type,
        "total": job.stats.total,
        "processed": job.stats.processed,
        "success": job.stats.success,
        "failed": job.stats.failed,
        "blocked": job.stats.blocked,
        "started_at": job.created_at,
    }

    try:

        await setter(
            f"{STATE_KEY_PREFIX}{job.admin_id}",
            payload,
        )

    except Exception:
        logger.exception(
            "Unable to save broadcast state"
        )


async def clear_broadcast_state(
    client: Client,
    admin_id: int,
):
    """
    Remove persisted broadcast state.
    """

    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is None:
        return

    for method_name in (
        "clear",
        "delete",
        "remove",
    ):

        method = getattr(
            state_manager,
            method_name,
            None,
        )

        if method is None:
            continue

        try:

            await method(
                f"{STATE_KEY_PREFIX}{int(admin_id)}"
            )

            return

        except Exception:
            logger.exception(
                "Unable to clear broadcast state"
            )

            return


# ============================================================================
# Target parsing
# ============================================================================

VALID_TARGET_TYPES = {
    "users",
    "groups",
    "all",
}


def normalize_target(
    value: Optional[str],
) -> str:

    if not value:
        return "users"

    value = (
        str(value)
        .strip()
        .lower()
    )

    aliases = {
        "user": "users",
        "users": "users",
        "pm": "users",
        "private": "users",
        "group": "groups",
        "groups": "groups",
        "chat": "groups",
        "chats": "groups",
        "all": "all",
    }

    return aliases.get(
        value,
        "users",
    )


async def resolve_recipients(
    client: Client,
    target_type: str,
) -> list[int]:

    target_type = normalize_target(
        target_type
    )

    if target_type == "users":

        return await get_user_ids(
            client
        )

    if target_type == "groups":

        return await get_group_ids(
            client
        )

    users = await get_user_ids(
        client
    )

    groups = await get_group_ids(
        client
    )

    return list(
        dict.fromkeys(
            users + groups
        )
    )


# ============================================================================
# Broadcast confirmation UI
# ============================================================================

def build_broadcast_confirmation_keyboard(
    job_id: str,
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👤 Users",
                    callback_data=(
                        f"broadcast:start:{job_id}:users"
                    ),
                ),
                InlineKeyboardButton(
                    "👥 Groups",
                    callback_data=(
                        f"broadcast:start:{job_id}:groups"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "🌐 Everyone",
                    callback_data=(
                        f"broadcast:start:{job_id}:all"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=(
                        f"broadcast:cancel:{job_id}"
                    ),
                ),
            ],
        ]
    )


def build_running_keyboard(
    job_id: str,
) -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛑 Stop Broadcast",
                    callback_data=(
                        f"broadcast:stop:{job_id}"
                    ),
                )
            ]
        ]
    )


def build_completed_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=(
                        "broadcast:close"
                    ),
                )
            ]
        ]
    )


# ============================================================================
# Confirmation text
# ============================================================================

def build_confirmation_text(
    job: BroadcastJob,
) -> str:

    return (
        "<b>📢 Broadcast Preview</b>\n\n"
        f"🆔 Job: <code>{escape_html(job.job_id)}</code>\n"
        f"📄 Source message: "
        f"<code>{job.source_message_id}</code>\n\n"
        "Choose the target audience:\n\n"
        "👤 <b>Users</b> — private users\n"
        "👥 <b>Groups</b> — registered groups\n"
        "🌐 <b>Everyone</b> — users + groups"
    )


# ============================================================================
# Progress formatting
# ============================================================================

def build_progress_text(
    job: BroadcastJob,
) -> str:

    stats = job.stats

    percent = stats.percentage

    bar_length = 12

    filled = int(
        (
            percent
            / 100
        )
        * bar_length
    )

    bar = (
        "█" * filled
        + "░"
        * (
            bar_length
            - filled
        )
    )

    eta = "N/A"

    if stats.rate > 0:

        eta_seconds = (
            stats.remaining
            / stats.rate
        )

        eta = format_duration(
            eta_seconds
        )

    status = (
        "🛑 Stopping..."
        if job.cancelled
        else "🚀 Running"
    )

    return (
        "<b>📢 Broadcast Progress</b>\n\n"
        f"{status}\n\n"
        f"[{bar}] "
        f"<b>{percent:.1f}%</b>\n\n"
        f"📦 Processed: "
        f"<b>{format_number(stats.processed)}</b>/"
        f"<b>{format_number(stats.total)}</b>\n"
        f"✅ Sent: "
        f"<b>{format_number(stats.success)}</b>\n"
        f"❌ Failed: "
        f"<b>{format_number(stats.failed)}</b>\n"
        f"🚫 Blocked: "
        f"<b>{format_number(stats.blocked)}</b>\n"
        f"🗑️ Deleted: "
        f"<b>{format_number(stats.deleted)}</b>\n"
        f"⚠️ Invalid: "
        f"<b>{format_number(stats.invalid)}</b>\n"
        f"⏳ Flood waits: "
        f"<b>{format_number(stats.flood_waits)}</b>\n\n"
        f"⚡ Speed: "
        f"<b>{stats.rate:.2f}/sec</b>\n"
        f"⏱️ Elapsed: "
        f"<b>{format_duration(stats.elapsed)}</b>\n"
        f"🕐 ETA: "
        f"<b>{escape_html(eta)}</b>"
    )


def build_completion_text(
    job: BroadcastJob,
) -> str:

    stats = job.stats

    if job.status == BROADCAST_STATE_CANCELLED:

        title = (
            "🛑 Broadcast Cancelled"
        )

    elif job.status == BROADCAST_STATE_FAILED:

        title = (
            "❌ Broadcast Failed"
        )

    else:

        title = (
            "✅ Broadcast Completed"
        )

    return (
        f"<b>{title}</b>\n\n"
        f"🆔 Job: <code>{escape_html(job.job_id)}</code>\n"
        f"🎯 Target: <b>{escape_html(job.target_type)}</b>\n\n"
        f"📦 Total: "
        f"<b>{format_number(stats.total)}</b>\n"
        f"⚡ Processed: "
        f"<b>{format_number(stats.processed)}</b>\n"
        f"✅ Successful: "
        f"<b>{format_number(stats.success)}</b>\n"
        f"❌ Failed: "
        f"<b>{format_number(stats.failed)}</b>\n"
        f"🚫 Blocked: "
        f"<b>{format_number(stats.blocked)}</b>\n"
        f"🗑️ Deleted: "
        f"<b>{format_number(stats.deleted)}</b>\n"
        f"⚠️ Invalid: "
        f"<b>{format_number(stats.invalid)}</b>\n"
        f"⏳ Flood waits: "
        f"<b>{format_number(stats.flood_waits)}</b>\n"
        f"🔁 Retries: "
        f"<b>{format_number(stats.retries)}</b>\n\n"
        f"⏱️ Duration: "
        f"<b>{format_duration(stats.elapsed)}</b>\n"
        f"⚡ Average speed: "
        f"<b>{stats.rate:.2f}/sec</b>"
    )


# ============================================================================
# Message copying
# ============================================================================

async def copy_broadcast_message(
    client: Client,
    source_chat_id: int,
    source_message_id: int,
    target_chat_id: int,
):
    """
    Copy a source message to a target chat.

    copy_message is intentionally used instead of downloading/re-uploading
    media. This is substantially more efficient for Telegram-to-Telegram
    broadcasts.
    """

    return await client.copy_message(
        chat_id=int(
            target_chat_id
        ),
        from_chat_id=int(
            source_chat_id
        ),
        message_id=int(
            source_message_id
        ),
    )


# ============================================================================
# Recipient error classification
# ============================================================================

def classify_delivery_error(
    error: Exception,
) -> str:

    if isinstance(
        error,
        UserIsBlocked,
    ):
        return "blocked"

    if isinstance(
        error,
        PeerIdInvalid,
    ):
        return "invalid"

    if isinstance(
        error,
        UserNotParticipant,
    ):
        return "invalid"

    if isinstance(
        error,
        MessageIdInvalid,
    ):
        return "deleted"

    return "failed"


# ============================================================================
# Send one recipient
# ============================================================================

async def send_to_recipient(
    client: Client,
    job: BroadcastJob,
    recipient_id: int,
) -> str:
    """
    Deliver to one recipient.

    Returns one of:

        success
        blocked
        invalid
        deleted
        failed
        cancelled
    """

    if job.is_cancelled():
        return "cancelled"

    attempt = 0

    while attempt <= job.max_retries:

        if job.is_cancelled():
            return "cancelled"

        try:

            await copy_broadcast_message(
                client,
                job.source_chat_id,
                job.source_message_id,
                recipient_id,
            )

            return "success"

        except FloodWait as error:

            job.stats.flood_waits += 1

            wait_seconds = int(
                getattr(
                    error,
                    "value",
                    getattr(
                        error,
                        "x",
                        1,
                    ),
                )
            )

            # Avoid absurd waits being treated as normal retries.
            wait_seconds = max(
                1,
                wait_seconds,
            )

            logger.warning(
                "Broadcast FloodWait: %ss",
                wait_seconds,
            )

            try:

                await asyncio.sleep(
                    wait_seconds
                )

            except asyncio.CancelledError:

                return "cancelled"

            continue

        except (
            UserIsBlocked,
            PeerIdInvalid,
            UserNotParticipant,
            MessageIdInvalid,
        ) as error:

            return classify_delivery_error(
                error
            )

        except Exception as error:

            job.stats.retries += 1

            job.stats.last_error = (
                str(error)
            )

            if attempt >= job.max_retries:

                logger.warning(
                    "Broadcast delivery failed "
                    "recipient=%s error=%s",
                    recipient_id,
                    error,
                )

                return classify_delivery_error(
                    error
                )

            attempt += 1

            try:

                await asyncio.sleep(
                    min(
                        2 ** attempt,
                        10,
                    )
                )

            except asyncio.CancelledError:

                return "cancelled"

    return "failed"


# ============================================================================
# Recipient processing
# ============================================================================

async def process_recipient(
    client: Client,
    job: BroadcastJob,
    recipient_id: int,
) -> str:

    result = await send_to_recipient(
        client,
        job,
        recipient_id,
    )

    if result == "success":

        job.stats.success += 1

    elif result == "blocked":

        job.stats.blocked += 1
        job.stats.failed += 1

    elif result == "deleted":

        job.stats.deleted += 1
        job.stats.failed += 1

    elif result == "invalid":

        job.stats.invalid += 1
        job.stats.failed += 1

    elif result == "cancelled":

        pass

    else:

        job.stats.failed += 1

    if result != "cancelled":

        job.stats.processed += 1

    return result


# ============================================================================
# Progress updater
# ============================================================================

async def update_progress_message(
    client: Client,
    job: BroadcastJob,
    *,
    force: bool = False,
):
    """
    Update the administrator's progress message.
    """

    if (
        not force
        and job.stats.processed
        % job.progress_interval
        != 0
    ):
        return

    if (
        job.progress_message_chat_id
        is None
        or job.progress_message_id
        is None
    ):
        return

    try:

        await client.edit_message_text(
            chat_id=job.progress_message_chat_id,
            message_id=job.progress_message_id,
            text=build_progress_text(
                job
            ),
            reply_markup=build_running_keyboard(
                job.job_id
            ),
        )

    except Exception as error:

        # MessageNotModified and similar harmless errors should not
        # terminate the broadcast.
        logger.debug(
            "Unable to update broadcast progress: %s",
            error,
        )


# ============================================================================
# Batch processing
# ============================================================================

async def process_batch(
    client: Client,
    job: BroadcastJob,
    recipients: Iterable[int],
):
    """
    Process one batch sequentially.

    Sequential delivery is intentional. Telegram FloodWait handling becomes
    much easier to control and we avoid creating thousands of concurrent
    requests.
    """

    for recipient_id in recipients:

        if job.is_cancelled():
            break

        await process_recipient(
            client,
            job,
            int(
                recipient_id
            ),
        )

        await update_progress_message(
            client,
            job,
        )

    if (
        not job.is_cancelled()
        and job.batch_delay > 0
    ):

        await asyncio.sleep(
            job.batch_delay
        )


# ============================================================================
# Main broadcast execution
# ============================================================================

async def run_broadcast(
    client: Client,
    job: BroadcastJob,
):
    """
    Execute a broadcast job.
    """

    job.running = True
    job.status = (
        BROADCAST_STATE_RUNNING
    )

    ACTIVE_BROADCASTS[
        job.job_id
    ] = job

    await save_broadcast_state(
        client,
        job,
    )

    try:

        recipients = await resolve_recipients(
            client,
            job.target_type,
        )

        # Remove duplicates and administrator itself.
        recipients = list(
            dict.fromkeys(
                int(item)
                for item in recipients
            )
        )

        recipients = [
            recipient
            for recipient in recipients
            if recipient != job.admin_id
        ]

        if len(
            recipients
        ) > MAX_BROADCAST_RECIPIENTS:

            recipients = recipients[
                :MAX_BROADCAST_RECIPIENTS
            ]

        job.recipients = recipients

        job.stats.total = len(
            recipients
        )

        await save_broadcast_state(
            client,
            job,
        )

        await update_progress_message(
            client,
            job,
            force=True,
        )

        if not recipients:

            job.status = (
                BROADCAST_STATE_COMPLETED
            )

            return

        # Batch processing.
        for start in range(
            0,
            len(recipients),
            job.batch_size,
        ):

            if job.is_cancelled():
                break

            batch = recipients[
                start:
                start + job.batch_size
            ]

            await process_batch(
                client,
                job,
                batch,
            )

            await save_broadcast_state(
                client,
                job,
            )

        if job.cancelled:

            job.status = (
                BROADCAST_STATE_CANCELLED
            )

        else:

            job.status = (
                BROADCAST_STATE_COMPLETED
            )

    except asyncio.CancelledError:

        job.cancel()

        raise

    except Exception as error:

        logger.exception(
            "Broadcast job failed: %s",
            job.job_id,
        )

        job.stats.last_error = (
            str(error)
        )

        job.status = (
            BROADCAST_STATE_FAILED
        )

    finally:

        job.running = False

        job.stats.finish()

        await save_broadcast_state(
            client,
            job,
        )

        await update_progress_message(
            client,
            job,
            force=True,
        )

        # Give the caller enough time to render completion before removing
        # the runtime registry entry.
        await asyncio.sleep(
            0
        )

        ACTIVE_BROADCASTS.pop(
            job.job_id,
            None,
        )

        await clear_broadcast_state(
            client,
            job.admin_id,
        )


# ============================================================================
# Begin broadcast
# ============================================================================

async def begin_broadcast(
    client: Client,
    message: Message,
):
    """
    Begin broadcast workflow.

    /broadcast must be used as a reply to the message that should be sent.
    """

    if not await require_admin(
        client,
        message,
    ):
        return

    user = message.from_user

    if user is None:
        return

    if message.reply_to_message is None:

        await message.reply_text(
            "<b>📢 Broadcast</b>\n\n"
            "Reply to the message you want to broadcast, "
            "then use:\n\n"
            "<code>/broadcast</code>\n\n"
            "The original message can contain text, media, "
            "documents, photos, videos, audio, or other supported content."
        )

        return

    admin_id = int(
        user.id
    )

    lock = get_admin_lock(
        admin_id
    )

    if lock.locked():

        await message.reply_text(
            "⚠️ <b>A broadcast is already running.</b>\n\n"
            "Stop it before starting another one."
        )

        return

    source = (
        message.reply_to_message
    )

    job = BroadcastJob(
        job_id=make_job_id(
            admin_id
        ),
        admin_id=admin_id,
        source_chat_id=int(
            source.chat.id
        ),
        source_message_id=int(
            source.id
        ),
    )

    await message.reply_text(
        build_confirmation_text(
            job
        ),
        reply_markup=build_broadcast_confirmation_keyboard(
            job.job_id
        ),
    )

    # Temporarily retain the job until the administrator chooses a target.
    ACTIVE_BROADCASTS[
        job.job_id
    ] = job


# ============================================================================
# Start callback
# ============================================================================

async def start_broadcast_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Confirm and start broadcast.
    """

    if not await require_admin_callback(
        client,
        callback_query,
    ):
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = "broadcast:start:"

    if not data.startswith(
        prefix
    ):
        return

    remainder = data[
        len(prefix):
    ]

    parts = remainder.split(
        ":",
        1,
    )

    if len(parts) != 2:
        return

    job_id, target_type = parts

    job = ACTIVE_BROADCASTS.get(
        job_id
    )

    if job is None:

        await callback_query.answer(
            "Broadcast session expired.",
            show_alert=True,
        )

        return

    if job.admin_id != int(
        callback_query.from_user.id
    ):

        await callback_query.answer(
            "This broadcast belongs to another administrator.",
            show_alert=True,
        )

        return

    target_type = normalize_target(
        target_type
    )

    job.target_type = target_type

    lock = get_admin_lock(
        job.admin_id
    )

    if lock.locked():

        await callback_query.answer(
            "Another broadcast is already running.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "🚀 Starting broadcast..."
    )

    if callback_query.message is None:
        return

    try:

        await callback_query.message.edit_text(
            "<b>⏳ Preparing broadcast...</b>\n\n"
            f"🎯 Target: <b>{escape_html(target_type)}</b>\n"
            "🔎 Collecting recipients..."
        )

    except Exception:
        pass

    async with lock:

        # Store progress message.
        if callback_query.message:

            job.progress_message_chat_id = int(
                callback_query.message.chat.id
            )

            job.progress_message_id = int(
                callback_query.message.id
            )

        job.status = (
            BROADCAST_STATE_RUNNING
        )

        task = asyncio.create_task(
            run_broadcast(
                client,
                job,
            )
        )

        job.task = task

        try:

            await task

        except asyncio.CancelledError:

            logger.info(
                "Broadcast task cancelled: %s",
                job.job_id,
            )

        finally:

            await finish_broadcast_message(
                client,
                job,
            )


# ============================================================================
# Finish UI
# ============================================================================

async def finish_broadcast_message(
    client: Client,
    job: BroadcastJob,
):
    """
    Replace progress UI with completion UI.
    """

    if (
        job.progress_message_chat_id
        is None
        or job.progress_message_id
        is None
    ):
        return

    try:

        await client.edit_message_text(
            chat_id=job.progress_message_chat_id,
            message_id=job.progress_message_id,
            text=build_completion_text(
                job
            ),
            reply_markup=build_completed_keyboard(),
        )

    except Exception:
        logger.exception(
            "Unable to display broadcast completion"
        )


# ============================================================================
# Stop callback
# ============================================================================

async def stop_broadcast_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Request graceful broadcast cancellation.
    """

    if not await require_admin_callback(
        client,
        callback_query,
    ):
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        "broadcast:stop:"
    )

    if not data.startswith(
        prefix
    ):
        return

    job_id = data[
        len(prefix):
    ]

    job = ACTIVE_BROADCASTS.get(
        job_id
    )

    if job is None:

        await callback_query.answer(
            "Broadcast is no longer active.",
            show_alert=True,
        )

        return

    if job.admin_id != int(
        callback_query.from_user.id
    ):

        await callback_query.answer(
            "This broadcast belongs to another administrator.",
            show_alert=True,
        )

        return

    job.cancel()

    await callback_query.answer(
        "🛑 Broadcast stopping..."
    )

    await save_broadcast_state(
        client,
        job,
    )

    await update_progress_message(
        client,
        job,
        force=True,
    )


# ============================================================================
# Cancel before start
# ============================================================================

async def cancel_broadcast_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Cancel a broadcast that has not started.
    """

    if not await require_admin_callback(
        client,
        callback_query,
    ):
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        "broadcast:cancel:"
    )

    if not data.startswith(
        prefix
    ):
        return

    job_id = data[
        len(prefix):
    ]

    job = ACTIVE_BROADCASTS.pop(
        job_id,
        None,
    )

    await callback_query.answer(
        "Broadcast cancelled."
    )

    if callback_query.message:

        try:

            await callback_query.message.edit_text(
                "<b>❌ Broadcast Cancelled</b>\n\n"
                "No messages were sent."
            )

        except Exception:
            pass

    if job:

        job.cancel()


# ============================================================================
# Close completion message
# ============================================================================

async def close_broadcast_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Close broadcast completion message.
    """

    if not await require_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

    if callback_query.message:

        try:

            await callback_query.message.delete()

        except Exception:

            try:

                await callback_query.message.edit_reply_markup(
                    reply_markup=None
                )

            except Exception:
                pass


# ============================================================================
# /broadcast stop
# ============================================================================

async def stop_command(
    client: Client,
    message: Message,
):
    """
    /stopbroadcast
    """

    if not await require_admin(
        client,
        message,
    ):
        return

    user = message.from_user

    if user is None:
        return

    admin_id = int(
        user.id
    )

    jobs = [
        job
        for job in ACTIVE_BROADCASTS.values()
        if job.admin_id == admin_id
        and job.running
    ]

    if not jobs:

        await message.reply_text(
            "ℹ️ No active broadcast."
        )

        return

    for job in jobs:

        job.cancel()

    await message.reply_text(
        "🛑 <b>Broadcast cancellation requested.</b>\n\n"
        "The current batch will finish and the broadcast will stop."
    )


# ============================================================================
# /broadcaststatus
# ============================================================================

async def broadcast_status_command(
    client: Client,
    message: Message,
):
    """
    Show active broadcast status.
    """

    if not await require_admin(
        client,
        message,
    ):
        return

    user = message.from_user

    if user is None:
        return

    jobs = [
        job
        for job in ACTIVE_BROADCASTS.values()
        if job.admin_id == int(
            user.id
        )
    ]

    if not jobs:

        await message.reply_text(
            "ℹ️ <b>No active broadcast.</b>"
        )

        return

    job = jobs[-1]

    await message.reply_text(
        build_progress_text(
            job
        ),
        reply_markup=(
            build_running_keyboard(
                job.job_id
            )
            if job.running
            else None
        ),
    )


# ============================================================================
# Broadcast history adapter
# ============================================================================

async def save_broadcast_result(
    client: Client,
    job: BroadcastJob,
):
    """
    Persist completed broadcast information when supported.

    This is optional so the bot remains compatible with the current
    database layer.
    """

    payload = {
        "job_id": job.job_id,
        "admin_id": job.admin_id,
        "target_type": job.target_type,
        "source_chat_id": job.source_chat_id,
        "source_message_id": job.source_message_id,
        "status": job.status,
        "total": job.stats.total,
        "processed": job.stats.processed,
        "success": job.stats.success,
        "failed": job.stats.failed,
        "blocked": job.stats.blocked,
        "deleted": job.stats.deleted,
        "invalid": job.stats.invalid,
        "flood_waits": job.stats.flood_waits,
        "retries": job.stats.retries,
        "created_at": job.created_at,
        "duration": job.stats.elapsed,
    }

    found, _ = await call_db_method(
        client,
        (
            "save_broadcast",
            "add_broadcast",
            "record_broadcast",
        ),
        payload,
    )

    if not found:
        return


# ============================================================================
# Enhanced run wrapper
# ============================================================================

async def execute_broadcast(
    client: Client,
    job: BroadcastJob,
):
    """
    Execute broadcast and persist its final result.
    """

    try:

        await run_broadcast(
            client,
            job,
        )

    finally:

        await save_broadcast_result(
            client,
            job,
        )


# ============================================================================
# Admin broadcast menu
# ============================================================================

async def broadcast_menu_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Show broadcast information.
    """

    if not await require_admin_callback(
        client,
        callback_query,
    ):
        return

    await callback_query.answer()

    if callback_query.message:

        await callback_query.message.edit_text(
            "<b>📢 Broadcast</b>\n\n"
            "Reply to any message and send:\n\n"
            "<code>/broadcast</code>\n\n"
            "The bot will let you choose:\n\n"
            "👤 Users\n"
            "👥 Groups\n"
            "🌐 Everyone\n\n"
            "Use <code>/stopbroadcast</code> to stop an active broadcast.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Admin Panel",
                            callback_data="admin_home",
                        )
                    ]
                ]
            ),
        )


# ============================================================================
# Admin broadcast stats
# ============================================================================

async def broadcast_stats_command(
    client: Client,
    message: Message,
):
    """
    /broadcaststats

    Display current active broadcast information.
    """

    if not await require_admin(
        client,
        message,
    ):
        return

    user = message.from_user

    if user is None:
        return

    admin_id = int(
        user.id
    )

    jobs = [
        job
        for job in ACTIVE_BROADCASTS.values()
        if job.admin_id == admin_id
    ]

    if not jobs:

        await message.reply_text(
            "📊 <b>Broadcast Statistics</b>\n\n"
            "No active broadcast."
        )

        return

    job = jobs[-1]

    await message.reply_text(
        build_progress_text(
            job
        )
    )


# ============================================================================
# Cleanup utility
# ============================================================================

async def cancel_all_broadcasts():
    """
    Gracefully mark all active jobs as cancelled.

    Useful during application shutdown.
    """

    jobs = list(
        ACTIVE_BROADCASTS.values()
    )

    for job in jobs:

        job.cancel()

        task = job.task

        if (
            task is not None
            and not task.done()
        ):

            task.cancel()

    ACTIVE_BROADCASTS.clear()


# ============================================================================
# Plugin handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "broadcast"
    )
)
async def broadcast_handler(
    client: Client,
    message: Message,
):
    await begin_broadcast(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "stopbroadcast"
    )
)
async def stop_broadcast_handler(
    client: Client,
    message: Message,
):
    await stop_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "broadcaststatus"
    )
)
async def broadcast_status_handler(
    client: Client,
    message: Message,
):
    await broadcast_status_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "broadcaststats"
    )
)
async def broadcast_stats_handler(
    client: Client,
    message: Message,
):
    await broadcast_stats_command(
        client,
        message,
    )


# ============================================================================
# Callback handlers
# ============================================================================

@Client.on_callback_query(
    filters.regex(
        r"^broadcast:start:"
    )
)
async def broadcast_start_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await start_broadcast_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^broadcast:stop:"
    )
)
async def broadcast_stop_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await stop_broadcast_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^broadcast:cancel:"
    )
)
async def broadcast_cancel_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await cancel_broadcast_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^broadcast:close$"
    )
)
async def broadcast_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await close_broadcast_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^broadcast:menu$"
    )
)
async def broadcast_menu_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await broadcast_menu_callback(
        client,
        callback_query,
    )


# ============================================================================
# Registration
# ============================================================================

def register(
    app: Client,
):
    """
    Register broadcast handlers.

    Do not use this registration system and Pyrogram plugin discovery
    simultaneously for the same handler in production.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    app.add_handler(
        MessageHandler(
            broadcast_handler,
            filters.command(
                "broadcast"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            stop_broadcast_handler,
            filters.command(
                "stopbroadcast"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            broadcast_status_handler,
            filters.command(
                "broadcaststatus"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            broadcast_stats_handler,
            filters.command(
                "broadcaststats"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            broadcast_start_handler,
            filters.regex(
                r"^broadcast:start:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            broadcast_stop_handler,
            filters.regex(
                r"^broadcast:stop:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            broadcast_cancel_handler,
            filters.regex(
                r"^broadcast:cancel:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            broadcast_close_handler,
            filters.regex(
                r"^broadcast:close$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            broadcast_menu_handler,
            filters.regex(
                r"^broadcast:menu$"
            ),
        )
    )

    logger.info(
        "Registered broadcast handlers"
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "BroadcastStats",
    "BroadcastJob",
    "ACTIVE_BROADCASTS",
    "begin_broadcast",
    "run_broadcast",
    "execute_broadcast",
    "stop_command",
    "broadcast_status_command",
    "broadcast_stats_command",
    "cancel_all_broadcasts",
    "build_progress_text",
    "build_completion_text",
    "register",
]