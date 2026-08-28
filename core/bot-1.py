"""
DOWNTOWN VILLA
File 4: core/bot.py

Central Telegram client factory.

Responsibilities:
    - Create the single shared Pyrogram client.
    - Read Telegram settings from config.py.
    - Keep client construction out of feature modules.
    - Provide a stable place for future client-level configuration.

This file intentionally does NOT contain:
    - commands
    - search
    - database operations
    - media indexing
    - admin logic
    - backup logic
    - feature-specific handlers

Those belong in their own modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pyrogram import Client

from config import CONFIG
from core.logging import get_logger


LOGGER = get_logger(__name__)

CLIENT_WORKDIR: Final[Path] = Path(__file__).resolve().parent.parent


def create_bot_client() -> Client:
    """
    Create and return the DOWNTOWN VILLA Telegram client.

    The client is created through one function so the rest of the project
    never needs to duplicate Telegram connection configuration.
    """
    telegram = CONFIG.telegram

    LOGGER.debug(
        "Creating %s Telegram client with session '%s'.",
        CONFIG.project_name,
        telegram.session_name,
    )

    client = Client(
        name=telegram.session_name,
        api_id=telegram.api_id,
        api_hash=telegram.api_hash,
        bot_token=telegram.bot_token,
        workdir=str(CLIENT_WORKDIR),
    )

    LOGGER.debug(
        "%s Telegram client created successfully.",
        CONFIG.project_name,
    )

    return client


# Public factory name for future modules.
get_bot_client = create_bot_client


__all__ = [
    "CLIENT_WORKDIR",
    "create_bot_client",
    "get_bot_client",
]
