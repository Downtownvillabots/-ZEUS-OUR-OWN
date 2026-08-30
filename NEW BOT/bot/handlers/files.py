"""
bot/handlers/files.py

File request and delivery entry-point handlers.

Flow
----
User search
    ↓
search service
    ↓
file results
    ↓
file selection callback
    ↓
verification check
    ↓
delivery service
    ↓
Telegram file

This module owns Telegram interaction/state only.
Search, verification, and delivery business logic remain in their
respective service modules.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

FILE_CALLBACK_PREFIX = "file"

MAX_CALLBACK_ID_LENGTH = 48


# ============================================================================
# Service loaders
# ============================================================================

def _load_service(
    module_name: str,
    names: tuple[str, ...],
):
    """
    Resolve a service object/function from bot.services.
    """

    try:

        module = __import__(
            f"bot.services.{module_name}",
            fromlist=["*"],
        )

    except ImportError:
        logger.exception(
            "Unable to import service: %s",
            module_name,
        )
        return None

    for name in names:

        service = getattr(
            module,
            name,
            None,
        )

        if service is not None:
            return service

    return module


def get_file_search_service():
    return _load_service(
        "file_search",
        (
            "file_search",
            "file_search_service",
            "FileSearchService",
        ),
    )


def get_delivery_service():
    return _load_service(
        "delivery",
        (
            "delivery",
            "delivery_service",
            "DeliveryService",
        ),
    )


def get_verification_service():
    return _load_service(
        "verification",
        (
            "verification",
            "verification_service",
            "VerificationService",
        ),
    )


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


async def call_method(
    service: Any,
    names: tuple[str, ...],
    **kwargs,
):
    """
    Call the first available service method.

    Returns:
        found, result
    """

    if service is None:
        return False, None

    for name in names:

        method = getattr(
            service,
            name,
            None,
        )

        if method is None:
            continue

        try:

            result = method(
                **kwargs
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            return True, result

        except TypeError:

            logger.exception(
                "Service method signature mismatch: %s",
                name,
            )

            return True, None

        except Exception:

            logger.exception(
                "Service method failed: %s",
                name,
            )

            return True, None

    return False, None


def get_value(
    result: Any,
    key: str,
    default: Any = None,
):
    """
    Read a value from dict/object.
    """

    if result is None:
        return default

    if isinstance(
        result,
        dict,
    ):
        return result.get(
            key,
            default,
        )

    return getattr(
        result,
        key,
        default,
    )


# ============================================================================
# Callback helpers
# ============================================================================

def clean_callback_value(
    value: Any,
) -> str:
    """
    Keep callback identifiers short and safe.
    """

    value = str(
        value or ""
    ).strip()

    return value[
        :MAX_CALLBACK_ID_LENGTH
    ]


def file_callback(
    file_id: Any,
) -> str:
    """
    Generate a file selection callback.
    """

    return (
        f"{FILE_CALLBACK_PREFIX}:open:"
        f"{clean_callback_value(file_id)}"
    )


def file_page_callback(
    page: int,
) -> str:

    return (
        f"{FILE_CALLBACK_PREFIX}:page:"
        f"{int(page)}"
    )


def file_back_callback() -> str:
    return (
        f"{FILE_CALLBACK_PREFIX}:back"
    )


def file_close_callback() -> str:
    return (
        f"{FILE_CALLBACK_PREFIX}:close"
    )


# ============================================================================
# Result normalization
# ============================================================================

def normalize_file(
    item: Any,
) -> dict[str, Any]:
    """
    Normalize a file/search result.

    Supports dictionaries and objects.
    """

    if isinstance(
        item,
        dict,
    ):

        return dict(
            item
        )

    fields = (
        "file_id",
        "id",
        "name",
        "file_name",
        "caption",
        "size",
        "file_size",
        "mime_type",
        "type",
        "message_id",
        "channel_id",
        "chat_id",
    )

    result = {}

    for field in fields:

        value = getattr(
            item,
            field,
            None,
        )

        if value is not None:
            result[field] = value

    return result


def extract_files(
    result: Any,
) -> list[dict[str, Any]]:
    """
    Normalize search result into a list of files.
    """

    if result is None:
        return []

    if isinstance(
        result,
        (list, tuple),
    ):

        return [
            normalize_file(
                item
            )
            for item in result
        ]

    if isinstance(
        result,
        dict,
    ):

        for key in (
            "files",
            "results",
            "items",
            "data",
        ):

            value = result.get(
                key
            )

            if isinstance(
                value,
                (list, tuple),
            ):

                return [
                    normalize_file(
                        item
                    )
                    for item in value
                ]

        if (
            "file_id" in result
            or "id" in result
        ):
            return [
                normalize_file(
                    result
                )
            ]

    return [
        normalize_file(
            result
        )
    ]


def get_file_identifier(
    file: dict[str, Any],
) -> Optional[str]:
    """
    Get the application's stable file identifier.
    """

    for key in (
        "file_id",
        "id",
        "_id",
        "message_id",
    ):

        value = file.get(
            key
        )

        if value is not None:

            return str(
                value
            )

    return None


def get_file_name(
    file: dict[str, Any],
) -> str:
    return str(
        file.get(
            "file_name"
        )
        or file.get(
            "name"
        )
        or file.get(
            "caption"
        )
        or "Unnamed file"
    )


def get_file_size(
    file: dict[str, Any],
) -> Optional[Any]:

    return (
        file.get(
            "file_size"
        )
        or file.get(
            "size"
        )
    )


def format_size(
    value: Any,
) -> str:
    """
    Format bytes.
    """

    if value is None:
        return "Unknown"

    try:
        value = float(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return str(
            value
        )

    if value <= 0:
        return "Unknown"

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    )

    index = 0

    while (
        value >= 1024
        and index < len(units) - 1
    ):

        value /= 1024
        index += 1

    return (
        f"{value:.2f} "
        f"{units[index]}"
    )


# ============================================================================
# File result UI
# ============================================================================

def build_file_keyboard(
    files: list[dict[str, Any]],
    *,
    page: int = 0,
    per_page: int = 8,
    total_pages: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Build file result keyboard.
    """

    if per_page <= 0:
        per_page = 8

    start = (
        page * per_page
    )

    end = (
        start + per_page
    )

    visible = files[
        start:end
    ]

    rows = []

    for index, file in enumerate(
        visible,
        start=start,
    ):

        file_id = get_file_identifier(
            file
        )

        if not file_id:
            continue

        name = get_file_name(
            file
        )

        # Telegram callback data has a strict byte limit.
        # Keep the visible button readable without using the filename
        # as callback data.
        label = (
            name[:55]
            if len(name) > 55
            else name
        )

        rows.append(
            [
                InlineKeyboardButton(
                    f"📄 {label}",
                    callback_data=file_callback(
                        file_id
                    ),
                )
            ]
        )

    if total_pages is None:

        total_pages = max(
            1,
            (
                len(files)
                + per_page
                - 1
            )
            // per_page,
        )

    navigation = []

    if page > 0:

        navigation.append(
            InlineKeyboardButton(
                "⬅️",
                callback_data=file_page_callback(
                    page - 1
                ),
            )
        )

    navigation.append(
        InlineKeyboardButton(
            f"📄 {page + 1}/{total_pages}",
            callback_data="file:no_action",
        )
    )

    if page < total_pages - 1:

        navigation.append(
            InlineKeyboardButton(
                "➡️",
                callback_data=file_page_callback(
                    page + 1
                ),
            )
        )

    if navigation:
        rows.append(
            navigation
        )

    rows.append(
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data=file_close_callback(),
            )
        ]
    )

    return InlineKeyboardMarkup(
        rows
    )


def build_file_text(
    files: list[dict[str, Any]],
    *,
    query: Optional[str] = None,
    page: int = 0,
    per_page: int = 8,
) -> str:
    """
    Format search result page.
    """

    total = len(
        files
    )

    if total == 0:

        return (
            "<b>📂 Files</b>\n\n"
            "❌ No matching files found."
        )

    start = (
        page * per_page
    )

    end = (
        start + per_page
    )

    visible = files[
        start:end
    ]

    lines = [
        "<b>📂 Search Results</b>",
        "",
    ]

    if query:

        lines.extend(
            [
                f"🔎 Query: "
                f"<code>{escape_html(query)}</code>",
                f"📊 Results: <b>{total}</b>",
                "",
            ]
        )

    for index, file in enumerate(
        visible,
        start=start + 1,
    ):

        name = get_file_name(
            file
        )

        size = format_size(
            get_file_size(
                file
            )
        )

        lines.append(
            f"<b>{index}.</b> "
            f"{escape_html(name[:80])}"
        )

        lines.append(
            f"   📦 {escape_html(size)}"
        )

    lines.extend(
        [
            "",
            "<i>Select a file below to continue.</i>",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================================
# Search service adapter
# ============================================================================

async def search_files(
    client: Client,
    query: str,
    *,
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Search files using file_search service.
    """

    service = get_file_search_service()

    if service is None:
        return []

    found, result = await call_method(
        service,
        (
            "search",
            "search_files",
            "find",
            "find_files",
            "get_files",
        ),
        query=query,
        chat_id=chat_id,
        user_id=user_id,
    )

    if not found:
        return []

    return extract_files(
        result
    )


# ============================================================================
# Store search state
# ============================================================================

async def save_file_search_state(
    client: Client,
    user_id: int,
    *,
    query: Optional[str],
    files: list[dict[str, Any]],
    page: int = 0,
):
    """
    Store search state.

    Uses state_manager when available.

    The state manager can later be replaced by Redis/database-backed state
    without changing this handler.
    """

    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is None:
        return

    payload = {
        "state": "file_results",
        "query": query,
        "files": files,
        "page": int(page),
    }

    setter = getattr(
        state_manager,
        "set",
        None,
    )

    if setter is None:
        return

    try:

        await setter(
            int(user_id),
            payload,
        )

    except Exception:
        logger.exception(
            "Unable to save file search state"
        )


async def get_file_search_state(
    client: Client,
    user_id: int,
) -> Optional[dict[str, Any]]:
    """
    Retrieve search state.
    """

    state_manager = getattr(
        client,
        "state_manager",
        None,
    )

    if state_manager is None:
        return None

    getter = getattr(
        state_manager,
        "get",
        None,
    )

    if getter is None:
        return None

    try:

        state = await getter(
            int(user_id)
        )

        if isinstance(
            state,
            dict,
        ):
            return state

    except Exception:
        logger.exception(
            "Unable to retrieve file search state"
        )

    return None


async def clear_file_search_state(
    client: Client,
    user_id: int,
):
    """
    Clear user file state.
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
                int(user_id)
            )

            return

        except Exception:
            logger.exception(
                "Unable to clear file state"
            )

            return


# ============================================================================
# File request
# ============================================================================

async def request_file(
    client: Client,
    message: Message,
    file_id: str,
) -> bool:
    """
    Request one file.

    Verification is checked before delivery.
    """

    user = message.from_user

    if user is None:
        return False

    file_id = str(
        file_id
    )

    # ------------------------------------------------------------------------
    # Verification gate.
    # ------------------------------------------------------------------------

    try:

        from bot.handlers.verification import (
            verify_before_file,
        )

        allowed = await verify_before_file(
            client,
            message,
            file_id,
        )

        if not allowed:

            # Verification UI has already been shown.
            return False

    except ImportError:

        logger.warning(
            "Verification handler unavailable; "
            "continuing without handler-level verification"
        )

    except Exception:

        logger.exception(
            "Verification gate failed"
        )

        await message.reply_text(
            "❌ Unable to check verification status."
        )

        return False

    # ------------------------------------------------------------------------
    # Delivery.
    # ------------------------------------------------------------------------

    delivery = get_delivery_service()

    if delivery is None:

        await message.reply_text(
            "❌ File delivery service is unavailable."
        )

        return False

    found, result = await call_method(
        delivery,
        (
            "deliver_file",
            "deliver",
            "send_file",
            "send",
            "handle_file",
        ),
        client=client,
        message=message,
        file_id=file_id,
        user_id=int(
            user.id
        ),
        chat_id=int(
            message.chat.id
        ),
    )

    if not found:

        await message.reply_text(
            "❌ File delivery method is not configured."
        )

        return False

    if result is False:

        await message.reply_text(
            "❌ Unable to deliver this file."
        )

        return False

    return True


# ============================================================================
# File callback
# ============================================================================

async def file_open_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Handle file selection.
    """

    user = callback_query.from_user

    if user is None:
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        f"{FILE_CALLBACK_PREFIX}:open:"
    )

    if not data.startswith(
        prefix
    ):
        return

    file_id = data[
        len(prefix):
    ]

    if not file_id:

        await callback_query.answer(
            "Invalid file.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "⏳ Preparing file..."
    )

    message = (
        callback_query.message
    )

    if message is None:
        return

    # Show a short processing state.
    try:

        await message.edit_text(
            "<b>⏳ Preparing your file...</b>\n\n"
            "Please wait."
        )

    except Exception:
        pass

    # Reconstruct delivery request.
    delivered = await request_file(
        client,
        message,
        file_id,
    )

    if not delivered:

        # Verification may have taken over the UI.
        return


# ============================================================================
# Page callback
# ============================================================================

async def file_page_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Navigate search results.
    """

    user = callback_query.from_user

    if user is None:
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        f"{FILE_CALLBACK_PREFIX}:page:"
    )

    if not data.startswith(
        prefix
    ):
        return

    try:

        page = int(
            data[
                len(prefix):
            ]
        )

    except ValueError:

        await callback_query.answer(
            "Invalid page.",
            show_alert=True,
        )

        return

    if page < 0:
        page = 0

    state = await get_file_search_state(
        client,
        int(
            user.id
        ),
    )

    if not state:

        await callback_query.answer(
            "Search session expired. Please search again.",
            show_alert=True,
        )

        return

    files = state.get(
        "files",
        []
    )

    if not isinstance(
        files,
        list,
    ):

        files = []

    query = state.get(
        "query"
    )

    per_page = int(
        state.get(
            "per_page",
            8,
        )
    )

    total_pages = max(
        1,
        (
            len(files)
            + per_page
            - 1
        )
        // per_page,
    )

    if page >= total_pages:
        page = total_pages - 1

    await save_file_search_state(
        client,
        int(
            user.id
        ),
        query=query,
        files=files,
        page=page,
    )

    await callback_query.answer()

    message = (
        callback_query.message
    )

    if message is None:
        return

    try:

        await message.edit_text(
            build_file_text(
                files,
                query=query,
                page=page,
                per_page=per_page,
            ),
            reply_markup=build_file_keyboard(
                files,
                page=page,
                per_page=per_page,
                total_pages=total_pages,
            ),
        )

    except Exception:
        logger.exception(
            "Unable to change file results page"
        )


# ============================================================================
# Back callback
# ============================================================================

async def file_back_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Return to previous search result page.
    """

    user = callback_query.from_user

    if user is None:
        return

    state = await get_file_search_state(
        client,
        int(
            user.id
        ),
    )

    if not state:

        await callback_query.answer(
            "Search session expired.",
            show_alert=True,
        )

        return

    files = state.get(
        "files",
        []
    )

    query = state.get(
        "query"
    )

    page = int(
        state.get(
            "page",
            0,
        )
    )

    per_page = int(
        state.get(
            "per_page",
            8,
        )
    )

    total_pages = max(
        1,
        (
            len(files)
            + per_page
            - 1
        )
        // per_page,
    )

    page = min(
        page,
        total_pages - 1,
    )

    await callback_query.answer()

    if callback_query.message:

        await callback_query.message.edit_text(
            build_file_text(
                files,
                query=query,
                page=page,
                per_page=per_page,
            ),
            reply_markup=build_file_keyboard(
                files,
                page=page,
                per_page=per_page,
                total_pages=total_pages,
            ),
        )


# ============================================================================
# Close callback
# ============================================================================

async def file_close_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Close file result UI.
    """

    user = callback_query.from_user

    if user:

        await clear_file_search_state(
            client,
            int(
                user.id
            ),
        )

    await callback_query.answer()

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
# No-op callback
# ============================================================================

async def file_no_action_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    await callback_query.answer()


# ============================================================================
# Search result entry point
# ============================================================================

async def show_file_results(
    client: Client,
    message: Message,
    files: list[dict[str, Any]],
    *,
    query: Optional[str] = None,
    page: int = 0,
):
    """
    Display normalized file results.
    """

    user = message.from_user

    if user is None:
        return

    per_page = 8

    total_pages = max(
        1,
        (
            len(files)
            + per_page
            - 1
        )
        // per_page,
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1,
        ),
    )

    await save_file_search_state(
        client,
        int(
            user.id
        ),
        query=query,
        files=files,
        page=page,
    )

    text = build_file_text(
        files,
        query=query,
        page=page,
        per_page=per_page,
    )

    keyboard = build_file_keyboard(
        files,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )

    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================================
# Search command
# ============================================================================

async def file_search_command(
    client: Client,
    message: Message,
):
    """
    /files <query>

    Direct file search command.
    """

    user = message.from_user

    if user is None:
        return

    command = (
        message.command
        or []
    )

    if len(command) < 2:

        await message.reply_text(
            "<b>Usage:</b>\n"
            "<code>/files movie name</code>\n\n"
            "You can also simply send the movie name."
        )

        return

    query = " ".join(
        command[1:]
    ).strip()

    if not query:

        await message.reply_text(
            "❌ Please provide a search query."
        )

        return

    status = await message.reply_text(
        "🔎 <b>Searching files...</b>"
    )

    try:

        files = await search_files(
            client,
            query,
            chat_id=int(
                message.chat.id
            ),
            user_id=int(
                user.id
            ),
        )

    except Exception:
        logger.exception(
            "File search failed"
        )

        await status.edit_text(
            "❌ File search failed. Please try again."
        )

        return

    try:

        await status.delete()

    except Exception:
        pass

    await show_file_results(
        client,
        message,
        files,
        query=query,
    )


# ============================================================================
# Generic file request callback
# ============================================================================

async def file_request_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Compatibility callback.

    Supports callback formats used by older file result UIs.
    """

    data = (
        callback_query.data
        or ""
    )

    if ":" not in data:
        return

    parts = data.split(
        ":",
        2,
    )

    if len(parts) != 3:
        return

    _, action, value = parts

    if action != "open":
        return

    # Reuse primary implementation.
    await file_open_callback(
        client,
        callback_query,
    )


# ============================================================================
# Pending file request support
# ============================================================================

async def store_pending_file(
    client: Client,
    user_id: int,
    file_id: str,
    *,
    chat_id: Optional[int] = None,
):
    """
    Store a pending file request.

    Used by verification flow.
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

    try:

        existing = await get_file_search_state(
            client,
            user_id,
        )

        payload = (
            existing
            if isinstance(
                existing,
                dict,
            )
            else {}
        )

        payload.update(
            {
                "pending_file_id": str(
                    file_id
                ),
                "pending_chat_id": (
                    int(chat_id)
                    if chat_id is not None
                    else None
                ),
            }
        )

        await setter(
            int(user_id),
            payload,
        )

    except Exception:
        logger.exception(
            "Unable to store pending file"
        )


async def get_pending_file(
    client: Client,
    user_id: int,
) -> Optional[str]:
    """
    Get pending file waiting for verification.
    """

    state = await get_file_search_state(
        client,
        user_id,
    )

    if not state:
        return None

    value = state.get(
        "pending_file_id"
    )

    if value is None:
        return None

    return str(
        value
    )


async def clear_pending_file(
    client: Client,
    user_id: int,
):
    """
    Remove pending file information while retaining other state.
    """

    state = await get_file_search_state(
        client,
        user_id,
    )

    if not state:
        return

    state.pop(
        "pending_file_id",
        None,
    )

    state.pop(
        "pending_chat_id",
        None,
    )

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

    try:

        await setter(
            int(user_id),
            state,
        )

    except Exception:
        logger.exception(
            "Unable to clear pending file"
        )


# ============================================================================
# Verification-aware delivery
# ============================================================================

async def deliver_with_verification(
    client: Client,
    message: Message,
    file_id: str,
) -> bool:
    """
    Central file access function.

    This should be used by other handlers/services whenever possible.
    """

    user = message.from_user

    if user is None:
        return False

    # ------------------------------------------------------------------------
    # Check verification.
    # ------------------------------------------------------------------------

    try:

        from bot.handlers.verification import (
            verify_before_file,
        )

        allowed = await verify_before_file(
            client,
            message,
            file_id,
        )

        if not allowed:

            await store_pending_file(
                client,
                int(
                    user.id
                ),
                file_id,
                chat_id=int(
                    message.chat.id
                ),
            )

            return False

    except ImportError:

        logger.warning(
            "Verification handler unavailable"
        )

    # ------------------------------------------------------------------------
    # Deliver.
    # ------------------------------------------------------------------------

    delivered = await request_file(
        client,
        message,
        file_id,
    )

    if delivered:

        await clear_pending_file(
            client,
            int(
                user.id
            ),
        )

    return delivered


# ============================================================================
# Plugin-compatible handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "files"
    )
)
async def files_command_handler(
    client: Client,
    message: Message,
):
    await file_search_command(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^file:open:"
    )
)
async def file_open_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_open_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^file:page:"
    )
)
async def file_page_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_page_callback_handler(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^file:back$"
    )
)
async def file_back_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_back_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^file:close$"
    )
)
async def file_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_close_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^file:no_action$"
    )
)
async def file_no_action_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await file_no_action_callback(
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
    Register file handlers.

    Normally the application should use either this registration mechanism
    OR Pyrogram plugin discovery, not both.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    app.add_handler(
        MessageHandler(
            file_search_command,
            filters.command(
                "files"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_open_callback,
            filters.regex(
                r"^file:open:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_page_callback_handler,
            filters.regex(
                r"^file:page:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_back_callback,
            filters.regex(
                r"^file:back$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_close_callback,
            filters.regex(
                r"^file:close$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            file_no_action_callback,
            filters.regex(
                r"^file:no_action$"
            ),
        )
    )

    logger.info(
        "Registered file handlers"
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "file_search_command",
    "files_command_handler",
    "file_open_callback",
    "file_page_callback_handler",
    "file_back_callback",
    "file_close_callback",
    "file_no_action_callback",
    "file_request_callback",
    "request_file",
    "deliver_with_verification",
    "show_file_results",
    "search_files",
    "store_pending_file",
    "get_pending_file",
    "clear_pending_file",
    "build_file_keyboard",
    "build_file_text",
    "register",
]