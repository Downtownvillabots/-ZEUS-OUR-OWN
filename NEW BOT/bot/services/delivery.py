"""
bot/services/delivery.py

Centralized Telegram file-delivery service.

Responsibilities:
    - Resolve stored file records.
    - Build deep links.
    - Deliver files to users.
    - Support protected content.
    - Handle FloodWait.
    - Handle blocked/deactivated users.
    - Schedule automatic deletion.
    - Keep Telegram delivery logic out of handlers.

This replaces scattered delivery logic from the old bot.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import Message

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_AUTO_DELETE = 0

MAX_RETRY_ATTEMPTS = 3

# Telegram deep-link payloads should remain reasonably small.
MAX_PAYLOAD_LENGTH = 64


# ============================================================================
# Result models
# ============================================================================

@dataclass
class DeliveryResult:
    """
    Result of a delivery attempt.
    """

    success: bool
    message: Optional[Message] = None
    error: Optional[str] = None
    deleted_user: bool = False
    retry_after: Optional[int] = None


@dataclass
class FileReference:
    """
    Normalized representation of a stored Telegram file.
    """

    file_id: str
    filename: str = ""
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    caption: Optional[str] = None


# ============================================================================
# File normalization
# ============================================================================

def normalize_file_record(
    record: dict,
) -> Optional[FileReference]:
    """
    Convert a MongoDB file document into FileReference.
    """
    if not record:
        return None

    file_id = (
        record.get("file_id")
        or record.get("telegram_file_id")
    )

    if not file_id:
        return None

    filename = (
        record.get("file_name")
        or record.get("filename")
        or record.get("name")
        or ""
    )

    file_size = (
        record.get("file_size")
        or record.get("size")
    )

    try:
        if file_size is not None:
            file_size = int(file_size)
    except (TypeError, ValueError):
        file_size = None

    return FileReference(
        file_id=str(file_id),
        filename=str(filename),
        file_size=file_size,
        file_type=(
            record.get("file_type")
            or record.get("media_type")
        ),
        chat_id=record.get("chat_id"),
        message_id=record.get("message_id"),
        caption=record.get("caption"),
    )


# ============================================================================
# Deep-link helpers
# ============================================================================

def create_file_payload(
    chat_id: int,
    file_id: str,
) -> str:
    """
    Create a compact callback/deep-link payload.

    Format:

        file_<chat_id>_<file_id>
    """
    payload = (
        f"file_{int(chat_id)}_{str(file_id)}"
    )

    if len(payload) > MAX_PAYLOAD_LENGTH:
        raise ValueError(
            "Generated file payload is too long"
        )

    return payload


def create_start_link(
    bot_username: str,
    chat_id: int,
    file_id: str,
) -> str:
    """
    Create Telegram bot deep link.

    Example:

        https://t.me/MyBot?start=file_-100123_ABC
    """
    username = str(
        bot_username or ""
    ).strip().lstrip("@")

    if not username:
        raise ValueError(
            "bot_username is required"
        )

    payload = create_file_payload(
        chat_id,
        file_id,
    )

    return (
        f"https://t.me/{username}"
        f"?start={payload}"
    )


# ============================================================================
# Caption helpers
# ============================================================================

def truncate_caption(
    caption: Optional[str],
    max_length: int = 1024,
) -> Optional[str]:
    """
    Telegram media captions have size limits.

    Keep this helper centralized so every delivery path behaves consistently.
    """
    if caption is None:
        return None

    caption = str(caption)

    if len(caption) <= max_length:
        return caption

    return (
        caption[: max_length - 3]
        + "..."
    )


def build_delivery_caption(
    file: FileReference,
    custom_caption: Optional[str] = None,
) -> Optional[str]:
    """
    Build the final caption.

    Priority:
        1. Explicit custom caption.
        2. Stored caption.
        3. No caption.
    """
    caption = (
        custom_caption
        if custom_caption is not None
        else file.caption
    )

    if not caption:
        return None

    return truncate_caption(
        caption
    )


# ============================================================================
# Media identification
# ============================================================================

def detect_media_type(
    file: FileReference,
) -> str:
    """
    Determine which Pyrogram send method should be used.

    Supported:
        photo
        video
        document
        audio
        animation
        voice
        video_note
        sticker

    Unknown types fall back to document.
    """
    if file.file_type:
        media_type = str(
            file.file_type
        ).lower()

        aliases = {
            "image": "photo",
            "pictures": "photo",
            "movie": "video",
            "file": "document",
            "music": "audio",
            "gif": "animation",
        }

        return aliases.get(
            media_type,
            media_type,
        )

    filename = (
        file.filename or ""
    ).lower()

    if filename.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        )
    ):
        return "photo"

    if filename.endswith(
        (
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
            ".webm",
        )
    ):
        return "video"

    if filename.endswith(
        (
            ".mp3",
            ".m4a",
            ".flac",
            ".wav",
            ".ogg",
        )
    ):
        return "audio"

    if filename.endswith(
        (
            ".gif",
        )
    ):
        return "animation"

    return "document"


# ============================================================================
# Telegram send implementation
# ============================================================================

async def _send_media(
    client: Client,
    chat_id: int | str,
    file: FileReference,
    caption: Optional[str],
    protect_content: bool = False,
) -> Message:
    """
    Send a stored Telegram file ID.
    """
    media_type = detect_media_type(
        file
    )

    kwargs = {
        "chat_id": chat_id,
        "caption": caption,
        "protect_content": protect_content,
    }

    # Remove None caption because some Pyrogram versions are stricter
    # depending on media type.
    if caption is None:
        kwargs.pop("caption")

    if media_type == "photo":
        return await client.send_photo(
            photo=file.file_id,
            **kwargs,
        )

    if media_type == "video":
        return await client.send_video(
            video=file.file_id,
            **kwargs,
        )

    if media_type == "audio":
        return await client.send_audio(
            audio=file.file_id,
            **kwargs,
        )

    if media_type == "animation":
        return await client.send_animation(
            animation=file.file_id,
            **kwargs,
        )

    if media_type == "voice":
        return await client.send_voice(
            voice=file.file_id,
            **kwargs,
        )

    if media_type == "video_note":
        # video_note doesn't support normal captions.
        return await client.send_video_note(
            video_note=file.file_id,
            chat_id=chat_id,
        )

    if media_type == "sticker":
        return await client.send_sticker(
            sticker=file.file_id,
            chat_id=chat_id,
        )

    # Safe fallback.
    return await client.send_document(
        document=file.file_id,
        **kwargs,
    )


# ============================================================================
# Retry handling
# ============================================================================

async def _send_with_retry(
    client: Client,
    chat_id: int | str,
    file: FileReference,
    caption: Optional[str],
    protect_content: bool,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
) -> DeliveryResult:
    """
    Send a file with FloodWait retry handling.
    """
    attempt = 0

    while attempt < max_attempts:
        attempt += 1

        try:
            message = await _send_media(
                client=client,
                chat_id=chat_id,
                file=file,
                caption=caption,
                protect_content=protect_content,
            )

            return DeliveryResult(
                success=True,
                message=message,
            )

        except FloodWait as exc:
            wait_seconds = int(
                getattr(
                    exc,
                    "value",
                    getattr(
                        exc,
                        "x",
                        1,
                    ),
                )
            )

            logger.warning(
                "FloodWait while delivering %s: "
                "sleeping %s seconds "
                "(attempt %s/%s)",
                file.file_id,
                wait_seconds,
                attempt,
                max_attempts,
            )

            if attempt >= max_attempts:
                return DeliveryResult(
                    success=False,
                    error="flood_wait",
                    retry_after=wait_seconds,
                )

            await asyncio.sleep(
                wait_seconds
            )

        except (
            InputUserDeactivated,
            UserIsBlocked,
            PeerIdInvalid,
        ) as exc:
            logger.info(
                "User %s cannot receive file %s: %s",
                chat_id,
                file.file_id,
                type(exc).__name__,
            )

            return DeliveryResult(
                success=False,
                error=type(exc).__name__,
                deleted_user=True,
            )

        except Exception as exc:
            logger.exception(
                "File delivery failed: %s",
                exc,
            )

            return DeliveryResult(
                success=False,
                error=str(exc),
            )

    return DeliveryResult(
        success=False,
        error="max_retries_exceeded",
    )


# ============================================================================
# Public delivery
# ============================================================================

async def deliver_file(
    client: Client,
    chat_id: int | str,
    file_record: dict | FileReference,
    custom_caption: Optional[str] = None,
    protect_content: bool = False,
    auto_delete: int = DEFAULT_AUTO_DELETE,
) -> DeliveryResult:
    """
    Deliver a file to a Telegram user/chat.

    Args:
        client:
            Running Pyrogram Client.

        chat_id:
            Destination Telegram chat.

        file_record:
            MongoDB document or FileReference.

        custom_caption:
            Optional caption override.

        protect_content:
            Prevent Telegram forwarding/saving where supported.

        auto_delete:
            Seconds before deleting the delivered message.
            0 disables automatic deletion.
    """
    if isinstance(
        file_record,
        FileReference,
    ):
        file = file_record
    else:
        file = normalize_file_record(
            file_record
        )

    if not file:
        return DeliveryResult(
            success=False,
            error="invalid_file_record",
        )

    caption = build_delivery_caption(
        file,
        custom_caption,
    )

    result = await _send_with_retry(
        client=client,
        chat_id=chat_id,
        file=file,
        caption=caption,
        protect_content=protect_content,
    )

    if (
        result.success
        and result.message
        and auto_delete
        and int(auto_delete) > 0
    ):
        schedule_auto_delete(
            result.message,
            int(auto_delete),
        )

    return result


# ============================================================================
# Auto-delete
# ============================================================================

async def delete_message_safely(
    message: Message,
) -> bool:
    """
    Delete a Telegram message without propagating errors.
    """
    try:
        await message.delete()
        return True
    except Exception as exc:
        logger.debug(
            "Unable to delete message %s: %s",
            getattr(message, "id", None),
            exc,
        )
        return False


async def _auto_delete_worker(
    message: Message,
    delay: int,
) -> None:
    """
    Background worker for automatic message deletion.
    """
    try:
        await asyncio.sleep(
            max(1, int(delay))
        )

        await delete_message_safely(
            message
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        logger.exception(
            "Auto-delete worker failed"
        )


def schedule_auto_delete(
    message: Message,
    delay: int,
) -> asyncio.Task:
    """
    Schedule deletion without blocking the handler.
    """
    return asyncio.create_task(
        _auto_delete_worker(
            message,
            delay,
        )
    )


# ============================================================================
# Batch delivery
# ============================================================================

async def deliver_files(
    client: Client,
    chat_id: int | str,
    files: list[dict | FileReference],
    custom_caption: Optional[str] = None,
    protect_content: bool = False,
    auto_delete: int = DEFAULT_AUTO_DELETE,
    delay_between: float = 0.0,
) -> list[DeliveryResult]:
    """
    Deliver multiple files sequentially.

    Sequential delivery is intentional. Telegram bots can easily hit
    FloodWait when sending large result batches concurrently.
    """
    results = []

    for file_record in files:
        result = await deliver_file(
            client=client,
            chat_id=chat_id,
            file_record=file_record,
            custom_caption=custom_caption,
            protect_content=protect_content,
            auto_delete=auto_delete,
        )

        results.append(
            result
        )

        if (
            delay_between > 0
            and result.success
        ):
            await asyncio.sleep(
                delay_between
            )

    return results


# ============================================================================
# Copy from source message
# ============================================================================

async def copy_message_safely(
    message: Message,
    chat_id: int | str,
    protect_content: bool = False,
) -> DeliveryResult:
    """
    Copy an existing Telegram message.

    This is useful when the original bot stores source channel/message
    references rather than only file IDs.
    """
    try:
        copied = await message.copy(
            chat_id=chat_id,
            protect_content=protect_content,
        )

        return DeliveryResult(
            success=True,
            message=copied,
        )

    except FloodWait as exc:
        wait_seconds = int(
            getattr(
                exc,
                "value",
                getattr(
                    exc,
                    "x",
                    1,
                ),
            )
        )

        return DeliveryResult(
            success=False,
            error="flood_wait",
            retry_after=wait_seconds,
        )

    except (
        InputUserDeactivated,
        UserIsBlocked,
        PeerIdInvalid,
    ) as exc:
        return DeliveryResult(
            success=False,
            error=type(exc).__name__,
            deleted_user=True,
        )

    except Exception as exc:
        logger.exception(
            "Unable to copy message: %s",
            exc,
        )

        return DeliveryResult(
            success=False,
            error=str(exc),
        )


# ============================================================================
# Source-message delivery
# ============================================================================

async def deliver_source_message(
    client: Client,
    destination_chat_id: int | str,
    source_chat_id: int | str,
    source_message_id: int,
    protect_content: bool = False,
    auto_delete: int = DEFAULT_AUTO_DELETE,
) -> DeliveryResult:
    """
    Fetch and copy a source Telegram message.

    This gives the new architecture a second delivery strategy:

        file_id delivery
        +
        source-message copy

    That is useful for files that should retain Telegram metadata.
    """
    try:
        messages = await client.get_messages(
            source_chat_id,
            source_message_id,
        )

        if not messages:
            return DeliveryResult(
                success=False,
                error="source_message_not_found",
            )

        message = messages

        result = await copy_message_safely(
            message=message,
            chat_id=destination_chat_id,
            protect_content=protect_content,
        )

        if (
            result.success
            and result.message
            and auto_delete
            and int(auto_delete) > 0
        ):
            schedule_auto_delete(
                result.message,
                int(auto_delete),
            )

        return result

    except Exception as exc:
        logger.exception(
            "Source message delivery failed: %s",
            exc,
        )

        return DeliveryResult(
            success=False,
            error=str(exc),
        )


# ============================================================================
# File availability
# ============================================================================

async def validate_file_id(
    client: Client,
    file_id: str,
) -> bool:
    """
    Validate whether Telegram can resolve a file ID.

    Pyrogram does not provide a cheap standalone "file exists" check for
    every media type, so this performs a minimal get-file operation.
    """
    if not file_id:
        return False

    try:
        await client.get_file(
            file_id
        )
        return True

    except Exception as exc:
        logger.debug(
            "Invalid Telegram file ID %s: %s",
            file_id,
            exc,
        )
        return False


# ============================================================================
# Delivery statistics
# ============================================================================

class DeliveryStats:
    """
    In-memory delivery statistics.

    These are process-local metrics. Production persistence/Prometheus
    integration can be added later without changing the delivery API.
    """

    def __init__(self):
        self.total_attempts = 0
        self.successful = 0
        self.failed = 0
        self.flood_waits = 0
        self.blocked_users = 0
        self.started_at = time.time()

    def record(
        self,
        result: DeliveryResult,
    ) -> None:
        self.total_attempts += 1

        if result.success:
            self.successful += 1
            return

        self.failed += 1

        if result.error == "flood_wait":
            self.flood_waits += 1

        if result.deleted_user:
            self.blocked_users += 1

    def snapshot(self) -> dict[str, Any]:
        uptime = (
            time.time()
            - self.started_at
        )

        success_rate = (
            self.successful
            / self.total_attempts
            * 100
            if self.total_attempts
            else 0.0
        )

        return {
            "total_attempts": self.total_attempts,
            "successful": self.successful,
            "failed": self.failed,
            "flood_waits": self.flood_waits,
            "blocked_users": self.blocked_users,
            "success_rate": round(
                success_rate,
                2,
            ),
            "uptime_seconds": round(
                uptime,
                2,
            ),
        }


delivery_stats = DeliveryStats()


# ============================================================================
# Tracked delivery
# ============================================================================

async def deliver_file_tracked(
    client: Client,
    chat_id: int | str,
    file_record: dict | FileReference,
    custom_caption: Optional[str] = None,
    protect_content: bool = False,
    auto_delete: int = DEFAULT_AUTO_DELETE,
) -> DeliveryResult:
    """
    Same as deliver_file(), but records process-local metrics.
    """
    result = await deliver_file(
        client=client,
        chat_id=chat_id,
        file_record=file_record,
        custom_caption=custom_caption,
        protect_content=protect_content,
        auto_delete=auto_delete,
    )

    delivery_stats.record(
        result
    )

    return result


# ============================================================================
# Convenience helpers
# ============================================================================

def get_delivery_filename(
    file_record: dict | FileReference,
) -> str:
    """
    Get a safe display filename.
    """
    if isinstance(
        file_record,
        FileReference,
    ):
        filename = file_record.filename
    else:
        filename = extract_filename(
            file_record
        )

    return str(
        filename or "File"
    ).strip()


def extract_filename(
    record: dict,
) -> str:
    """
    Compatibility helper for older code.
    """
    return (
        record.get("file_name")
        or record.get("filename")
        or record.get("name")
        or "File"
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "DeliveryResult",
    "FileReference",
    "DeliveryStats",
    "delivery_stats",
    "normalize_file_record",
    "detect_media_type",
    "build_delivery_caption",
    "create_file_payload",
    "create_start_link",
    "deliver_file",
    "deliver_file_tracked",
    "deliver_files",
    "deliver_source_message",
    "copy_message_safely",
    "delete_message_safely",
    "schedule_auto_delete",
    "validate_file_id",
    "get_delivery_filename",
]