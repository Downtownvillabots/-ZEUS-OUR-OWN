"""
bot/handlers/start.py

/start handler and Telegram deep-link entry point.

Supported start modes:

    /start
    /start <payload>

Reserved payload prefixes:

    file_
    verify_
    verification_
    request_
    req_
    ref_

The handler intentionally delegates business logic to services.
"""

from __future__ import annotations

import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Payload constants
# ============================================================================

FILE_PREFIXES = (
    "file_",
)

VERIFICATION_PREFIXES = (
    "verify_",
    "verification_",
)

REQUEST_PREFIXES = (
    "request_",
    "req_",
)

REFERRAL_PREFIXES = (
    "ref_",
    "referral_",
)


# ============================================================================
# Text
# ============================================================================

START_TEXT = """
<b>🎬 Welcome to {bot_name}!</b>

━━━━━━━━━━━━━━━━━━━━

🔎 <b>Search</b>
Send me the name of a movie, series, or file to search.

📂 <b>Files</b>
I can help you find available files from the database.

⚡ <b>Fast Search</b>
Use a simple movie or series name and I'll find the closest results.

━━━━━━━━━━━━━━━━━━━━

<i>Send a search query to get started.</i>
"""


# ============================================================================
# Helpers
# ============================================================================

def get_bot_name(
    client: Client,
) -> str:
    """
    Get bot display name.

    Uses cached Telegram information when available.
    """

    me = getattr(
        client,
        "me",
        None,
    )

    if me:

        if getattr(
            me,
            "first_name",
            None,
        ):
            return me.first_name

        if getattr(
            me,
            "username",
            None,
        ):
            return f"@{me.username}"

    return "Dream Bot"


def build_start_keyboard() -> InlineKeyboardMarkup:
    """
    Main start-menu keyboard.

    Keep callback names stable because other handlers will use them.
    """

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔎 Search",
                    callback_data="menu_search",
                ),
            ],
            [
                InlineKeyboardButton(
                    "ℹ️ Help",
                    callback_data="menu_help",
                ),
                InlineKeyboardButton(
                    "⚙️ Settings",
                    callback_data="menu_settings",
                ),
            ],
        ]
    )


def parse_start_payload(
    message: Message,
) -> Optional[str]:
    """
    Extract the /start payload.

    Example:

        /start file_123

    returns:

        file_123
    """

    command = getattr(
        message,
        "command",
        None,
    )

    if not command:
        return None

    if len(command) < 2:
        return None

    payload = str(
        command[1]
    ).strip()

    return payload or None


def classify_payload(
    payload: Optional[str],
) -> tuple[str, Optional[str]]:
    """
    Determine the type of a deep-link payload.

    Returns:

        ("normal", None)
        ("file", "...")
        ("verification", "...")
        ("request", "...")
        ("referral", "...")
        ("unknown", "...")
    """

    if not payload:
        return (
            "normal",
            None,
        )

    payload_lower = payload.lower()

    for prefix in FILE_PREFIXES:
        if payload_lower.startswith(prefix):
            return (
                "file",
                payload[len(prefix):],
            )

    for prefix in VERIFICATION_PREFIXES:
        if payload_lower.startswith(prefix):
            return (
                "verification",
                payload[len(prefix):],
            )

    for prefix in REQUEST_PREFIXES:
        if payload_lower.startswith(prefix):
            return (
                "request",
                payload[len(prefix):],
            )

    for prefix in REFERRAL_PREFIXES:
        if payload_lower.startswith(prefix):
            return (
                "referral",
                payload[len(prefix):],
            )

    return (
        "unknown",
        payload,
    )


# ============================================================================
# User registration
# ============================================================================

async def ensure_user(
    client: Client,
    message: Message,
) -> bool:
    """
    Register the Telegram user if necessary.

    Database initialization is deliberately obtained from the application
    object instead of importing a global database here.

    Expected:

        client.db

    to be configured during application startup.
    """

    user = message.from_user

    if user is None:
        return False

    db = getattr(
        client,
        "db",
        None,
    )

    if db is None:
        logger.warning(
            "Database is not attached to client"
        )
        return False

    user_id = int(
        user.id
    )

    try:

        exists = await db.is_user_exist(
            user_id
        )

        if not exists:

            name = (
                user.first_name
                or user.username
                or str(user_id)
            )

            await db.add_user(
                user_id,
                name,
            )

            logger.info(
                "Registered new user %s",
                user_id,
            )

        return True

    except Exception:
        logger.exception(
            "Failed to register user %s",
            user_id,
        )

        return False


# ============================================================================
# Ban check
# ============================================================================

async def is_user_banned(
    client: Client,
    user_id: int,
) -> bool:
    """
    Check whether a user is banned.

    Returns False if the database is unavailable so the handler doesn't
    crash during application startup.
    """

    db = getattr(
        client,
        "db",
        None,
    )

    if db is None:
        return False

    try:

        status = await db.get_ban_status(
            int(user_id)
        )

        return bool(
            status.get(
                "is_banned",
                False,
            )
        )

    except Exception:
        logger.exception(
            "Unable to check ban status for %s",
            user_id,
        )

        return False


# ============================================================================
# Deep-link handlers
# ============================================================================

async def handle_file_payload(
    client: Client,
    message: Message,
    payload: str,
) -> bool:
    """
    Handle:

        /start file_<payload>

    The actual file delivery service will be connected here later.
    """

    try:

        from bot.services.delivery import delivery

    except ImportError:
        delivery = None

    if delivery is None:

        await message.reply_text(
            "❌ File delivery is currently unavailable."
        )

        return False

    try:

        # The delivery service can later expose:
        #
        #   deliver_from_payload(...)
        #
        # We keep this adapter isolated so the /start handler itself
        # doesn't need to know database/file implementation details.

        handler = getattr(
            delivery,
            "deliver_from_payload",
            None,
        )

        if handler is None:

            await message.reply_text(
                "📂 File delivery is being prepared."
            )

            return False

        result = await handler(
            client=client,
            message=message,
            payload=payload,
        )

        return bool(
            result
        )

    except Exception:
        logger.exception(
            "File deep-link failed: %s",
            payload,
        )

        await message.reply_text(
            "❌ Unable to open this file right now."
        )

        return False


async def handle_verification_payload(
    client: Client,
    message: Message,
    payload: str,
) -> bool:
    """
    Handle verification deep links.

        /start verify_<token>
    """

    try:

        from bot.services.verification import (
            verification,
        )

    except ImportError:
        verification = None

    if verification is None:

        await message.reply_text(
            "❌ Verification service is unavailable."
        )

        return False

    user = message.from_user

    if user is None:
        return False

    try:

        result = await verification.consume_token(
            int(user.id),
            payload,
        )

        if not result.success:

            await message.reply_text(
                "❌ <b>Verification failed.</b>\n\n"
                "This verification link may be invalid or expired."
            )

            return False

        await message.reply_text(
            "✅ <b>Verification successful!</b>\n\n"
            "You can now continue using the bot."
        )

        return True

    except Exception:
        logger.exception(
            "Verification deep-link failed for user %s",
            user.id,
        )

        await message.reply_text(
            "❌ Something went wrong while verifying your account."
        )

        return False


async def handle_request_payload(
    client: Client,
    message: Message,
    payload: str,
) -> bool:
    """
    Handle request deep links.

        /start request_<payload>
    """

    # Request service/handler will be connected once requests.py is built.
    #
    # Keeping this route now means the public deep-link format doesn't
    # need to change later.

    try:

        from bot.services import requests as request_service

    except ImportError:
        request_service = None

    if request_service is None:

        await message.reply_text(
            "📝 Request service is currently unavailable."
        )

        return False

    handler = getattr(
        request_service,
        "handle_start_payload",
        None,
    )

    if handler is None:

        await message.reply_text(
            "📝 This request link is not available yet."
        )

        return False

    try:

        result = await handler(
            client=client,
            message=message,
            payload=payload,
        )

        return bool(
            result
        )

    except Exception:
        logger.exception(
            "Request deep-link failed: %s",
            payload,
        )

        await message.reply_text(
            "❌ Unable to open this request."
        )

        return False


async def handle_referral_payload(
    client: Client,
    message: Message,
    payload: str,
) -> bool:
    """
    Handle referral links.

    Referral support is intentionally lightweight now.
    The referral/premium system can attach its own logic later.
    """

    user = message.from_user

    if user is None:
        return False

    db = getattr(
        client,
        "db",
        None,
    )

    try:

        if db is not None:

            # Do not automatically award anything here.
            #
            # Store the referral relationship only if the database layer
            # supports it.

            method = getattr(
                db,
                "set_referrer",
                None,
            )

            if method is not None:

                try:

                    referrer_id = int(
                        payload
                    )

                except ValueError:
                    referrer_id = None

                if (
                    referrer_id
                    and referrer_id != int(user.id)
                ):
                    await method(
                        int(user.id),
                        referrer_id,
                    )

        await send_start_message(
            client,
            message,
        )

        return True

    except Exception:
        logger.exception(
            "Referral payload failed"
        )

        await send_start_message(
            client,
            message,
        )

        return True


# ============================================================================
# Main /start response
# ============================================================================

async def send_start_message(
    client: Client,
    message: Message,
):
    """
    Send the main welcome message.
    """

    bot_name = get_bot_name(
        client
    )

    text = START_TEXT.format(
        bot_name=bot_name
    )

    await message.reply_text(
        text,
        reply_markup=build_start_keyboard(),
        disable_web_page_preview=True,
    )


# ============================================================================
# /start router
# ============================================================================

async def start_command(
    client: Client,
    message: Message,
):
    """
    Main /start handler.
    """

    user = message.from_user

    if user is None:
        return

    user_id = int(
        user.id
    )

    # ------------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------------

    await ensure_user(
        client,
        message,
    )

    # ------------------------------------------------------------------------
    # Ban protection
    # ------------------------------------------------------------------------

    if await is_user_banned(
        client,
        user_id,
    ):

        await message.reply_text(
            "🚫 <b>You are banned from using this bot.</b>"
        )

        return

    # ------------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------------

    payload = parse_start_payload(
        message
    )

    payload_type, value = (
        classify_payload(
            payload
        )
    )

    # ------------------------------------------------------------------------
    # Normal start
    # ------------------------------------------------------------------------

    if payload_type == "normal":

        await send_start_message(
            client,
            message,
        )

        return

    # ------------------------------------------------------------------------
    # File deep-link
    # ------------------------------------------------------------------------

    if payload_type == "file":

        if not value:

            await send_start_message(
                client,
                message,
            )

            return

        await handle_file_payload(
            client,
            message,
            value,
        )

        return

    # ------------------------------------------------------------------------
    # Verification deep-link
    # ------------------------------------------------------------------------

    if payload_type == "verification":

        if not value:

            await message.reply_text(
                "❌ Invalid verification link."
            )

            return

        await handle_verification_payload(
            client,
            message,
            value,
        )

        return

    # ------------------------------------------------------------------------
    # Request deep-link
    # ------------------------------------------------------------------------

    if payload_type == "request":

        if not value:

            await message.reply_text(
                "❌ Invalid request link."
            )

            return

        await handle_request_payload(
            client,
            message,
            value,
        )

        return

    # ------------------------------------------------------------------------
    # Referral deep-link
    # ------------------------------------------------------------------------

    if payload_type == "referral":

        if not value:

            await send_start_message(
                client,
                message,
            )

            return

        await handle_referral_payload(
            client,
            message,
            value,
        )

        return

    # ------------------------------------------------------------------------
    # Unknown payload
    # ------------------------------------------------------------------------

    logger.warning(
        "Unknown /start payload from %s: %s",
        user_id,
        payload,
    )

    await send_start_message(
        client,
        message,
    )


# ============================================================================
# Handler registration
# ============================================================================

def register(
    app: Client,
):
    """
    Register /start handler on the supplied Pyrogram application.

    This explicit registration approach keeps startup predictable and makes
    testing easier.
    """

    app.add_handler(
        # Imported lazily so this module can be imported in tests without
        # requiring all application components to be initialized.
        __import__(
            "pyrogram.handlers",
            fromlist=[
                "MessageHandler"
            ],
        ).MessageHandler(
            start_command,
            filters.command(
                "start"
            ),
        )
    )

    logger.info(
        "Registered /start handler"
    )


# ============================================================================
# Pyrogram plugin-compatible handler
# ============================================================================

@Client.on_message(
    filters.command(
        "start"
    )
)
async def start_handler(
    client: Client,
    message: Message,
):
    """
    Pyrogram plugin entry point.

    app.py uses:

        plugins={"root": "bot.handlers"}

    or this module can be registered manually.
    """

    await start_command(
        client,
        message,
    )


__all__ = [
    "start_command",
    "start_handler",
    "send_start_message",
    "parse_start_payload",
    "classify_payload",
    "ensure_user",
    "register",
]