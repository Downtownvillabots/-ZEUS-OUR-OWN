"""
Telegram-specific helper functions.
"""

from __future__ import annotations

from typing import Optional

from telegram import (
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.ext import ContextTypes


def get_user_id(
    update: Update,
) -> Optional[int]:

    if update.effective_user is None:
        return None

    return int(
        update.effective_user.id
    )


def get_chat_id(
    update: Update,
) -> Optional[int]:

    if update.effective_chat is None:
        return None

    return int(
        update.effective_chat.id
    )


def get_message(
    update: Update,
) -> Optional[Message]:

    return update.effective_message


def get_text(
    update: Update,
) -> str:

    message = update.effective_message

    if message is None:
        return ""

    return (
        message.text
        or message.caption
        or ""
    )


def get_command(
    update: Update,
) -> Optional[str]:

    text = get_text(
        update
    ).strip()

    if not text.startswith("/"):
        return None

    command = text.split(
        maxsplit=1
    )[0]

    return command.split(
        "@",
        maxsplit=1,
    )[0]


def get_callback_data(
    update: Update,
) -> Optional[str]:

    callback = (
        update.callback_query
    )

    if callback is None:
        return None

    return callback.data


async def answer_callback(
    update: Update,
    text: Optional[str] = None,
    *,
    show_alert: bool = False,
) -> bool:

    callback = (
        update.callback_query
    )

    if callback is None:
        return False

    try:

        await callback.answer(
            text=text,
            show_alert=show_alert,
        )

        return True

    except Exception:
        return False


async def edit_message(
    update: Update,
    text: str,
    *,
    reply_markup: Optional[
        InlineKeyboardMarkup
    ] = None,
    parse_mode: Optional[str] = None,
) -> bool:

    callback = (
        update.callback_query
    )

    if callback is not None:

        try:

            await callback.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )

            return True

        except Exception:
            pass

    message = update.effective_message

    if message is None:
        return False

    try:

        await message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

        return True

    except Exception:

        return False


async def safe_reply(
    update: Update,
    text: str,
    *,
    reply_markup: Optional[
        InlineKeyboardMarkup
    ] = None,
    parse_mode: Optional[str] = None,
) -> Optional[Message]:

    message = update.effective_message

    if message is None:
        return None

    try:

        return await message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    except Exception:
        return None


def context_request_id(
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[str]:

    value = context.user_data.get(
        "request_id"
    )

    return (
        str(value)
        if value is not None
        else None
    )


__all__ = [
    "get_user_id",
    "get_chat_id",
    "get_message",
    "get_text",
    "get_command",
    "get_callback_data",
    "answer_callback",
    "edit_message",
    "safe_reply",
    "context_request_id",
]