"""
bot/handlers/verification.py

Telegram verification handlers.

Responsibilities
----------------
- Verification status UI
- Verification buttons
- Verification token links
- Verification callbacks
- Verification retry
- Verification cancellation
- Returning users to a requested file
- Integration with services/verification.py

Architecture
------------

Telegram
   |
   v
verification.py
   |
   +---- services/verification.py
   |
   +---- database/verification.py
   |
   +---- delivery.py
   |
   v
Verified file access

Important
---------
This module intentionally does NOT implement token generation,
token validation, expiry calculations, or database persistence itself.

Those responsibilities belong to:

    bot/services/verification.py
    bot/database/verification.py
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pyrogram import Client, filters
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

CALLBACK_PREFIX = "verification"

DEFAULT_EXPIRY_MINUTES = 30

MAX_PAYLOAD_LENGTH = 128


# ============================================================================
# Text
# ============================================================================

VERIFICATION_REQUIRED_TEXT = """
<b>🔐 Verification Required</b>

━━━━━━━━━━━━━━━━━━━━

To continue accessing this file, you need to complete
the verification process.

This helps protect the bot from automated abuse.

━━━━━━━━━━━━━━━━━━━━

<b>What to do?</b>

1️⃣ Press <b>Verify</b>
2️⃣ Complete the verification process
3️⃣ Return to the bot
4️⃣ Your requested file will continue automatically

━━━━━━━━━━━━━━━━━━━━

<i>Your verification status will be checked automatically.</i>
"""

VERIFICATION_SUCCESS_TEXT = """
<b>✅ Verification Successful</b>

━━━━━━━━━━━━━━━━━━━━

Your account has been verified successfully.

You can now continue using the requested file.

━━━━━━━━━━━━━━━━━━━━
"""

VERIFICATION_FAILED_TEXT = """
<b>❌ Verification Failed</b>

━━━━━━━━━━━━━━━━━━━━

We could not verify your account.

The verification link may be:

• Expired
• Invalid
• Already used
• Associated with another request

Please try again.
"""

VERIFICATION_EXPIRED_TEXT = """
<b>⏰ Verification Expired</b>

━━━━━━━━━━━━━━━━━━━━

Your verification session has expired.

Please create a new verification session to continue.
"""

VERIFICATION_PROCESSING_TEXT = """
<b>⏳ Checking Verification</b>

Please wait while we check your verification status...
"""

VERIFICATION_CANCELLED_TEXT = """
<b>❌ Verification Cancelled</b>

The verification process has been cancelled.

You can request verification again whenever you need it.
"""


# ============================================================================
# Service discovery
# ============================================================================

def get_verification_service():
    """
    Resolve the verification service.

    The project may expose it under slightly different names depending
    on the service implementation, so this function supports common forms.
    """

    try:

        from bot.services import verification as module

    except ImportError:
        logger.exception(
            "Unable to import verification service"
        )

        return None

    service = getattr(
        module,
        "verification",
        None,
    )

    if service is not None:
        return service

    service = getattr(
        module,
        "verification_service",
        None,
    )

    if service is not None:
        return service

    # Some implementations expose a class instead.
    service_class = getattr(
        module,
        "VerificationService",
        None,
    )

    if service_class is not None:

        try:
            return service_class()
        except Exception:
            logger.exception(
                "Unable to instantiate VerificationService"
            )

    return module


# ============================================================================
# Delivery service discovery
# ============================================================================

def get_delivery_service():
    """
    Resolve file delivery service.
    """

    try:

        from bot.services import delivery as module

    except ImportError:
        logger.exception(
            "Unable to import delivery service"
        )

        return None

    service = getattr(
        module,
        "delivery",
        None,
    )

    if service is not None:
        return service

    service = getattr(
        module,
        "delivery_service",
        None,
    )

    if service is not None:
        return service

    return module


# ============================================================================
# Generic service invocation
# ============================================================================

async def call_service_method(
    service: Any,
    method_names: tuple[str, ...],
    **kwargs,
):
    """
    Call the first available asynchronous service method.

    This adapter lets the handler remain compatible while the service layer
    evolves.

    Returns:

        (found, result)

    where found indicates whether a method existed.
    """

    if service is None:
        return False, None

    for method_name in method_names:

        method = getattr(
            service,
            method_name,
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
            # Some service methods may use positional arguments or a
            # slightly different signature. We intentionally don't silently
            # retry with arbitrary positional parameters here because doing
            # so could hide real bugs.
            logger.exception(
                "Verification service method signature mismatch: %s",
                method_name,
            )

            return True, None

        except Exception:
            logger.exception(
                "Verification service method failed: %s",
                method_name,
            )

            return True, None

    return False, None


# ============================================================================
# Result interpretation
# ============================================================================

def result_success(
    result: Any,
) -> bool:
    """
    Normalize different service response formats.

    Supported:

        True
        {"success": True}
        {"verified": True}
        {"allowed": True}
        object.success
        object.verified
        object.allowed
    """

    if result is True:
        return True

    if result is False or result is None:
        return False

    if isinstance(
        result,
        dict,
    ):

        for key in (
            "success",
            "verified",
            "allowed",
            "valid",
        ):

            if key in result:
                return bool(
                    result[key]
                )

        return False

    for attribute in (
        "success",
        "verified",
        "allowed",
        "valid",
    ):

        value = getattr(
            result,
            attribute,
            None,
        )

        if value is not None:
            return bool(
                value
            )

    return False


def result_value(
    result: Any,
    key: str,
    default: Any = None,
) -> Any:
    """
    Read a value from dict/object service response.
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
# Payload helpers
# ============================================================================

def clean_payload(
    payload: Optional[str],
) -> str:
    """
    Normalize verification payload.
    """

    if not payload:
        return ""

    value = str(
        payload
    ).strip()

    if len(value) > MAX_PAYLOAD_LENGTH:
        value = value[
            :MAX_PAYLOAD_LENGTH
        ]

    return value


def build_verification_callback(
    token: str,
) -> str:
    """
    Build callback_data for an existing verification token.

    Tokens should normally be short opaque identifiers.
    """

    token = clean_payload(
        token
    )

    if not token:
        return (
            "verification:invalid"
        )

    return (
        f"verification:check:{token}"
    )


def build_verification_cancel_callback() -> str:
    return (
        "verification:cancel"
    )


def build_verification_retry_callback() -> str:
    return (
        "verification:retry"
    )


# ============================================================================
# Verification keyboard
# ============================================================================

def build_verification_keyboard(
    verification_url: Optional[str] = None,
    token: Optional[str] = None,
    show_cancel: bool = True,
) -> InlineKeyboardMarkup:
    """
    Build verification keyboard.

    If an external verification URL is available, the Verify button opens
    that URL.

    If no URL exists, a callback-based verification check is shown.
    """

    rows = []

    if verification_url:

        rows.append(
            [
                InlineKeyboardButton(
                    "🔐 Verify",
                    url=verification_url,
                )
            ]
        )

    elif token:

        rows.append(
            [
                InlineKeyboardButton(
                    "🔐 Verify",
                    callback_data=build_verification_callback(
                        token
                    ),
                )
            ]
        )

    else:

        rows.append(
            [
                InlineKeyboardButton(
                    "🔄 Check Verification",
                    callback_data=(
                        "verification:retry"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔄 Check Again",
                callback_data=(
                    "verification:retry"
                ),
            )
        ]
    )

    if show_cancel:

        rows.append(
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data=(
                        "verification:cancel"
                    ),
                )
            ]
        )

    return InlineKeyboardMarkup(
        rows
    )


# ============================================================================
# Verification request model
# ============================================================================

def build_request_context(
    *,
    user_id: int,
    chat_id: Optional[int] = None,
    file_id: Optional[str] = None,
    message_id: Optional[int] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a normalized verification context.
    """

    return {
        "user_id": int(
            user_id
        ),
        "chat_id": (
            int(chat_id)
            if chat_id is not None
            else None
        ),
        "file_id": (
            str(file_id)
            if file_id is not None
            else None
        ),
        "message_id": (
            int(message_id)
            if message_id is not None
            else None
        ),
        "token": clean_payload(
            token
        ),
        "created_at": int(
            time.time()
        ),
    }


# ============================================================================
# Service: status
# ============================================================================

async def get_verification_status(
    client: Client,
    user_id: int,
    chat_id: Optional[int] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """
    Ask verification service for current status.
    """

    service = get_verification_service()

    if service is None:
        return {
            "allowed": False,
            "verified": False,
            "success": False,
            "reason": "service_unavailable",
        }

    found, result = await call_service_method(
        service,
        (
            "get_status",
            "check_status",
            "status",
            "get_verification_status",
        ),
        user_id=int(
            user_id
        ),
        chat_id=(
            int(chat_id)
            if chat_id is not None
            else None
        ),
        token=clean_payload(
            token
        ),
    )

    if not found:

        return {
            "allowed": False,
            "verified": False,
            "success": False,
            "reason": "unsupported_service",
        }

    if isinstance(
        result,
        dict,
    ):

        return result

    return {
        "allowed": result_success(
            result
        ),
        "verified": result_success(
            result
        ),
        "success": result_success(
            result
        ),
        "raw": result,
    }


# ============================================================================
# Service: create verification
# ============================================================================

async def create_verification(
    client: Client,
    *,
    user_id: int,
    chat_id: Optional[int] = None,
    file_id: Optional[str] = None,
    message_id: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """
    Create a verification session.

    The service decides how the token and verification URL are generated.
    """

    service = get_verification_service()

    if service is None:
        return None

    context = build_request_context(
        user_id=user_id,
        chat_id=chat_id,
        file_id=file_id,
        message_id=message_id,
    )

    found, result = await call_service_method(
        service,
        (
            "create_verification",
            "create_session",
            "generate_verification",
            "create_token",
            "generate_token",
        ),
        **context,
    )

    if not found:
        return None

    if isinstance(
        result,
        dict,
    ):
        return result

    return {
        "success": result_success(
            result
        ),
        "raw": result,
    }


# ============================================================================
# Verification request UI
# ============================================================================

async def show_verification_required(
    client: Client,
    message: Message,
    *,
    token: Optional[str] = None,
    verification_url: Optional[str] = None,
    file_id: Optional[str] = None,
):
    """
    Display verification requirement.
    """

    text = (
        VERIFICATION_REQUIRED_TEXT
    )

    if file_id:

        text += (
            "\n"
            f"📂 Requested file: "
            f"<code>{escape_html(file_id)}</code>\n"
        )

    keyboard = build_verification_keyboard(
        verification_url=verification_url,
        token=token,
    )

    await message.reply_text(
        text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ============================================================================
# Start verification flow
# ============================================================================

async def start_verification(
    client: Client,
    message: Message,
    *,
    file_id: Optional[str] = None,
    chat_id: Optional[int] = None,
    message_id: Optional[int] = None,
):
    """
    Start a verification session for a user.
    """

    user = message.from_user

    if user is None:
        return False

    user_id = int(
        user.id
    )

    if chat_id is None:
        chat_id = int(
            message.chat.id
        )

    # ------------------------------------------------------------------------
    # Check whether verification is already satisfied.
    # ------------------------------------------------------------------------

    status = await get_verification_status(
        client,
        user_id,
        chat_id,
    )

    if (
        result_success(
            status
        )
        or bool(
            status.get(
                "allowed",
                False,
            )
        )
    ):

        return await continue_after_verification(
            client,
            message,
            file_id=file_id,
            verification_result=status,
        )

    # ------------------------------------------------------------------------
    # Create new verification session.
    # ------------------------------------------------------------------------

    session = await create_verification(
        client,
        user_id=user_id,
        chat_id=chat_id,
        file_id=file_id,
        message_id=message_id,
    )

    if not session:

        await message.reply_text(
            "❌ <b>Unable to create a verification session.</b>\n\n"
            "Please try again later."
        )

        return False

    token = (
        session.get(
            "token"
        )
        or session.get(
            "verification_token"
        )
    )

    verification_url = (
        session.get(
            "url"
        )
        or session.get(
            "verification_url"
        )
        or session.get(
            "link"
        )
    )

    # Service may explicitly report failure.
    if (
        "success" in session
        and not session.get(
            "success"
        )
        and not token
        and not verification_url
    ):

        await message.reply_text(
            "❌ <b>Unable to start verification.</b>\n\n"
            "Please try again later."
        )

        return False

    await show_verification_required(
        client,
        message,
        token=token,
        verification_url=verification_url,
        file_id=file_id,
    )

    return True


# ============================================================================
# Verify callback
# ============================================================================

async def verify_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Verify a token from callback_data.

    Callback format:

        verification:check:<token>
    """

    user = callback_query.from_user

    if user is None:
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        "verification:check:"
    )

    if not data.startswith(
        prefix
    ):

        await callback_query.answer(
            "Invalid verification request.",
            show_alert=True,
        )

        return

    token = clean_payload(
        data[len(prefix):]
    )

    if not token:

        await callback_query.answer(
            "Invalid verification token.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "⏳ Checking verification..."
    )

    message = (
        callback_query.message
    )

    if message is None:
        return

    user_id = int(
        user.id
    )

    chat_id = int(
        message.chat.id
    )

    service = get_verification_service()

    if service is None:

        await message.edit_text(
            "❌ Verification service is currently unavailable."
        )

        return

    found, result = await call_service_method(
        service,
        (
            "verify_token",
            "consume_token",
            "verify",
            "check_token",
            "validate_token",
        ),
        user_id=user_id,
        chat_id=chat_id,
        token=token,
    )

    if not found:

        await message.edit_text(
            "❌ Verification service does not support token validation yet."
        )

        return

    if not result_success(
        result
    ):

        reason = result_value(
            result,
            "reason",
            "",
        )

        if str(
            reason
        ).lower() in {
            "expired",
            "token_expired",
            "session_expired",
        }:

            await show_expired_verification(
                client,
                message,
            )

            return

        await show_failed_verification(
            client,
            message,
            reason=reason,
        )

        return

    await show_success_verification(
        client,
        message,
        verification_result=result,
    )


# ============================================================================
# Retry callback
# ============================================================================

async def retry_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Re-check current verification state.
    """

    user = callback_query.from_user

    if user is None:
        return

    message = (
        callback_query.message
    )

    if message is None:
        return

    await callback_query.answer(
        "⏳ Checking..."
    )

    user_id = int(
        user.id
    )

    chat_id = int(
        message.chat.id
    )

    try:

        status = await get_verification_status(
            client,
            user_id,
            chat_id,
        )

        if result_success(
            status
        ) or bool(
            status.get(
                "allowed",
                False,
            )
        ):

            await show_success_verification(
                client,
                message,
                verification_result=status,
            )

            return

        reason = status.get(
            "reason",
            "",
        )

        if str(
            reason
        ).lower() in {
            "expired",
            "token_expired",
            "session_expired",
        }:

            await show_expired_verification(
                client,
                message,
            )

            return

        # Still waiting.
        await message.edit_text(
            VERIFICATION_REQUIRED_TEXT,
            reply_markup=build_verification_keyboard(),
        )

    except Exception:
        logger.exception(
            "Verification retry failed"
        )

        await message.edit_text(
            "❌ Unable to check verification right now.\n\n"
            "Please try again.",
            reply_markup=build_verification_keyboard(),
        )


# ============================================================================
# Cancel callback
# ============================================================================

async def cancel_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Cancel the current verification session.
    """

    user = callback_query.from_user

    if user is None:
        return

    await callback_query.answer(
        "Verification cancelled."
    )

    message = (
        callback_query.message
    )

    if message is None:
        return

    service = get_verification_service()

    if service is not None:

        try:

            await call_service_method(
                service,
                (
                    "cancel",
                    "cancel_session",
                    "invalidate",
                    "delete_session",
                ),
                user_id=int(
                    user.id
                ),
                chat_id=int(
                    message.chat.id
                ),
            )

        except Exception:
            logger.exception(
                "Unable to cancel verification session"
            )

    try:

        await message.edit_text(
            VERIFICATION_CANCELLED_TEXT
        )

    except Exception:
        logger.exception(
            "Unable to display cancellation message"
        )


# ============================================================================
# Result screens
# ============================================================================

async def show_success_verification(
    client: Client,
    message: Message,
    *,
    verification_result: Any = None,
):
    """
    Show successful verification and continue any pending file request.
    """

    try:

        await message.edit_text(
            VERIFICATION_SUCCESS_TEXT
        )

    except Exception:
        try:

            await message.reply_text(
                VERIFICATION_SUCCESS_TEXT
            )

        except Exception:
            logger.exception(
                "Unable to display verification success"
            )

    # Extract a pending file from service result if available.
    file_id = result_value(
        verification_result,
        "file_id",
        None,
    )

    if file_id is None:
        file_id = result_value(
            verification_result,
            "pending_file_id",
            None,
        )

    if file_id:

        await continue_file_delivery(
            client,
            message,
            str(file_id),
        )


async def show_failed_verification(
    client: Client,
    message: Message,
    *,
    reason: Any = None,
):
    """
    Display failed verification.
    """

    text = (
        VERIFICATION_FAILED_TEXT
    )

    if reason:

        text += (
            "\n"
            f"Reason: <code>"
            f"{escape_html(reason)}"
            f"</code>"
        )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Try Again",
                    callback_data=(
                        "verification:retry"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=(
                        "verification:cancel"
                    ),
                )
            ],
        ]
    )

    try:

        await message.edit_text(
            text,
            reply_markup=keyboard,
        )

    except Exception:

        await message.reply_text(
            text,
            reply_markup=keyboard,
        )


async def show_expired_verification(
    client: Client,
    message: Message,
):
    """
    Display expired verification.
    """

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔄 Start Again",
                    callback_data=(
                        "verification:retry"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=(
                        "verification:cancel"
                    ),
                )
            ],
        ]
    )

    try:

        await message.edit_text(
            VERIFICATION_EXPIRED_TEXT,
            reply_markup=keyboard,
        )

    except Exception:

        await message.reply_text(
            VERIFICATION_EXPIRED_TEXT,
            reply_markup=keyboard,
        )


# ============================================================================
# Continue after verification
# ============================================================================

async def continue_after_verification(
    client: Client,
    message: Message,
    *,
    file_id: Optional[str] = None,
    verification_result: Any = None,
) -> bool:
    """
    Continue a pending request after verification.

    The file ID can come directly from the caller or from the verification
    service response.
    """

    if file_id is None:

        file_id = result_value(
            verification_result,
            "file_id",
            None,
        )

    if file_id is None:

        file_id = result_value(
            verification_result,
            "pending_file_id",
            None,
        )

    if file_id is None:

        await message.reply_text(
            "✅ <b>Verification complete.</b>\n\n"
            "You can now request your file again."
        )

        return True

    return await continue_file_delivery(
        client,
        message,
        str(file_id),
    )


async def continue_file_delivery(
    client: Client,
    message: Message,
    file_id: str,
) -> bool:
    """
    Ask delivery service to continue delivery.
    """

    delivery = get_delivery_service()

    if delivery is None:

        await message.reply_text(
            "✅ Verification successful.\n\n"
            "❌ File delivery service is currently unavailable."
        )

        return False

    # Preferred service method.
    found, result = await call_service_method(
        delivery,
        (
            "deliver_file",
            "deliver",
            "send_file",
            "handle_file_selection",
        ),
        client=client,
        message=message,
        file_id=file_id,
    )

    if not found:

        await message.reply_text(
            "✅ Verification successful.\n\n"
            "📂 Please request the file again."
        )

        return False

    if result is False:

        await message.reply_text(
            "❌ Verification succeeded, but file delivery failed."
        )

        return False

    return True


# ============================================================================
# /verify
# ============================================================================

async def verify_command(
    client: Client,
    message: Message,
):
    """
    /verify

    Check or start verification manually.
    """

    user = message.from_user

    if user is None:
        return

    user_id = int(
        user.id
    )

    chat_id = int(
        message.chat.id
    )

    status = await get_verification_status(
        client,
        user_id,
        chat_id,
    )

    if result_success(
        status
    ) or bool(
        status.get(
            "allowed",
            False,
        )
    ):

        await message.reply_text(
            "✅ <b>You are already verified.</b>\n\n"
            "You can continue using the bot."
        )

        return

    await start_verification(
        client,
        message,
    )


# ============================================================================
# /verification
# ============================================================================

async def verification_command(
    client: Client,
    message: Message,
):
    """
    Alias for /verify.
    """

    await verify_command(
        client,
        message,
    )


# ============================================================================
# Verification status command
# ============================================================================

async def verification_status_command(
    client: Client,
    message: Message,
):
    """
    /verification_status

    Show current verification state.
    """

    user = message.from_user

    if user is None:
        return

    status = await get_verification_status(
        client,
        int(
            user.id
        ),
        int(
            message.chat.id
        ),
    )

    if result_success(
        status
    ) or bool(
        status.get(
            "allowed",
            False,
        )
    ):

        await message.reply_text(
            "🔐 <b>Verification Status</b>\n\n"
            "✅ Verified\n\n"
            "You currently have access."
        )

        return

    reason = status.get(
        "reason",
        "Verification required",
    )

    await message.reply_text(
        "🔐 <b>Verification Status</b>\n\n"
        "❌ Not verified\n\n"
        f"Reason: <code>{escape_html(reason)}</code>",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔄 Verify",
                        callback_data=(
                            "verification:retry"
                        ),
                    )
                ]
            ]
        ),
    )


# ============================================================================
# File verification entry point
# ============================================================================

async def verify_before_file(
    client: Client,
    message: Message,
    file_id: str,
) -> bool:
    """
    Entry point used by delivery/file handlers.

    Returns True when delivery can proceed immediately.

    Returns False when verification was required or failed.
    """

    user = message.from_user

    if user is None:
        return False

    user_id = int(
        user.id
    )

    chat_id = int(
        message.chat.id
    )

    status = await get_verification_status(
        client,
        user_id,
        chat_id,
    )

    if (
        result_success(
            status
        )
        or bool(
            status.get(
                "allowed",
                False,
            )
        )
    ):

        return True

    # Verification is required.
    await start_verification(
        client,
        message,
        file_id=file_id,
        chat_id=chat_id,
    )

    return False


# ============================================================================
# HTML helper
# ============================================================================

def escape_html(
    value: Any,
) -> str:
    """
    Escape Telegram HTML.
    """

    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============================================================================
# Registration
# ============================================================================

def register(
    app: Client,
):
    """
    Register verification handlers.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    # ------------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------------

    app.add_handler(
        MessageHandler(
            verify_command,
            filters.command(
                "verify"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            verification_command,
            filters.command(
                "verification"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            verification_status_command,
            filters.command(
                "verification_status"
            ),
        )
    )

    # ------------------------------------------------------------------------
    # Verification callbacks
    # ------------------------------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            verify_callback,
            filters.regex(
                r"^verification:check:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            retry_callback,
            filters.regex(
                r"^verification:retry$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            cancel_callback,
            filters.regex(
                r"^verification:cancel$"
            ),
        )
    )

    logger.info(
        "Registered verification handlers"
    )


# ============================================================================
# Plugin-compatible handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "verify"
    )
)
async def verify_handler(
    client: Client,
    message: Message,
):
    await verify_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "verification"
    )
)
async def verification_handler(
    client: Client,
    message: Message,
):
    await verification_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "verification_status"
    )
)
async def verification_status_handler(
    client: Client,
    message: Message,
):
    await verification_status_command(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^verification:check:"
    )
)
async def verification_check_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await verify_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^verification:retry$"
    )
)
async def verification_retry_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await retry_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^verification:cancel$"
    )
)
async def verification_cancel_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await cancel_callback(
        client,
        callback_query,
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "verification_command",
    "verify_command",
    "verification_status_command",
    "verify_before_file",
    "start_verification",
    "get_verification_status",
    "create_verification",
    "verify_callback",
    "retry_callback",
    "cancel_callback",
    "show_verification_required",
    "show_success_verification",
    "show_failed_verification",
    "show_expired_verification",
    "continue_after_verification",
    "continue_file_delivery",
    "build_verification_keyboard",
    "register",
]