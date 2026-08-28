"""
DOWNTOWN VILLA
File 6: core/constants.py

Central project-wide constants.

Purpose:
    Keep values that are reused across multiple modules in one obvious place.

Examples of values that belong here:
    - project branding
    - callback prefixes
    - pagination defaults
    - common limits
    - internal names
    - reusable identifiers

Values that contain secrets or environment-specific settings do NOT belong
here. Those belong in config.py / environment variables.

User-facing captions and buttons will eventually get their own dedicated
messages/ and keyboards/ modules. This file should not become a giant
collection of every piece of text in the bot.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Project identity
# ---------------------------------------------------------------------------

PROJECT_NAME: Final[str] = "DOWNTOWN VILLA"
PROJECT_SHORT_NAME: Final[str] = "DOWNTOWN VILLA"
PROJECT_VERSION: Final[str] = "0.1.0"


# ---------------------------------------------------------------------------
# Package names
# ---------------------------------------------------------------------------

CORE_PACKAGE: Final[str] = "core"
PLUGINS_PACKAGE: Final[str] = "plugins"
DATABASE_PACKAGE: Final[str] = "database"
UTILS_PACKAGE: Final[str] = "utils"
MESSAGES_PACKAGE: Final[str] = "messages"
KEYBOARDS_PACKAGE: Final[str] = "keyboards"


# ---------------------------------------------------------------------------
# Callback namespaces
# ---------------------------------------------------------------------------
#
# Callback data will be built around namespaces so different features do not
# accidentally use the same callback prefix.
#
# Examples later:
#     start:...
#     search:...
#     file:...
#     admin:...
#

CALLBACK_START: Final[str] = "start"
CALLBACK_HELP: Final[str] = "help"
CALLBACK_SEARCH: Final[str] = "search"
CALLBACK_FILE: Final[str] = "file"
CALLBACK_ADMIN: Final[str] = "admin"
CALLBACK_BACKUP: Final[str] = "backup"
CALLBACK_PREMIUM: Final[str] = "premium"
CALLBACK_STATS: Final[str] = "stats"
CALLBACK_NAV: Final[str] = "nav"


# ---------------------------------------------------------------------------
# File callback settings
# ---------------------------------------------------------------------------

FILE_CALLBACK_SEPARATOR: Final[str] = "#"
FILE_CALLBACK_PREFIX: Final[str] = f"{CALLBACK_FILE}{FILE_CALLBACK_SEPARATOR}"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE: Final[int] = 10
MIN_PAGE_SIZE: Final[int] = 1
MAX_PAGE_SIZE: Final[int] = 100

DEFAULT_MAX_SEARCH_RESULTS: Final[int] = 100


# ---------------------------------------------------------------------------
# General operational limits
# ---------------------------------------------------------------------------

MAX_CALLBACK_DATA_LENGTH: Final[int] = 64

DEFAULT_OPERATION_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_TELEGRAM_TIMEOUT_SECONDS: Final[float] = 30.0

DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
DEFAULT_RETRY_DELAY_SECONDS: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Media-related constants
# ---------------------------------------------------------------------------

# Telegram cached-media behavior is a core design principle of this project.
# Actual sending logic belongs in the media service later.
USE_CACHED_TELEGRAM_MEDIA: Final[bool] = True

# Stored media should normally be referenced by Telegram file_id rather than
# downloaded and uploaded again.
PRIMARY_MEDIA_IDENTIFIER: Final[str] = "file_id"


# ---------------------------------------------------------------------------
# Database identifiers
# ---------------------------------------------------------------------------
#
# These are logical names, not connection strings.
# Actual database URLs and credentials belong in config.py/environment.
#

PRIMARY_MEDIA_DATABASE: Final[str] = "Media"

MEDIA_DATABASE_PREFIX: Final[str] = "Media"

MEDIA_DATABASE_NAMES: Final[tuple[str, ...]] = (
    "Media",
    "Media2",
    "Media3",
)


# ---------------------------------------------------------------------------
# Logging identifiers
# ---------------------------------------------------------------------------

LOGGER_ROOT_NAME: Final[str] = "downtown_villa"


# ---------------------------------------------------------------------------
# Environment names
# ---------------------------------------------------------------------------
#
# Keeping the names centralized makes configuration changes easier and
# avoids spelling differences between modules.
#

ENV_API_ID: Final[str] = "API_ID"
ENV_API_HASH: Final[str] = "API_HASH"
ENV_BOT_TOKEN: Final[str] = "BOT_TOKEN"
ENV_SESSION_NAME: Final[str] = "SESSION_NAME"

ENV_DATABASE_URL: Final[str] = "DATABASE_URL"
ENV_MEDIA_DATABASE_URLS: Final[str] = "MEDIA_DATABASE_URLS"

ENV_ADMIN_IDS: Final[str] = "ADMIN_IDS"
ENV_OWNER_IDS: Final[str] = "OWNER_IDS"

ENV_BACKUP_ENABLED: Final[str] = "BACKUP_ENABLED"
ENV_BACKUP_CHANNEL_ID: Final[str] = "BACKUP_CHANNEL_ID"
ENV_BACKUP_DELAY: Final[str] = "BACKUP_DELAY"

ENV_ENABLE_SEARCH: Final[str] = "ENABLE_SEARCH"
ENV_SEARCH_PAGE_SIZE: Final[str] = "SEARCH_PAGE_SIZE"
ENV_MAX_SEARCH_RESULTS: Final[str] = "MAX_SEARCH_RESULTS"

ENV_ENABLE_BACKUP: Final[str] = "ENABLE_BACKUP"
ENV_ENABLE_PREMIUM: Final[str] = "ENABLE_PREMIUM"
ENV_ENABLE_STATISTICS: Final[str] = "ENABLE_STATISTICS"

ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"
ENV_LOG_TO_FILE: Final[str] = "LOG_TO_FILE"
ENV_LOG_DIR: Final[str] = "LOG_DIR"
ENV_LOG_FILE: Final[str] = "LOG_FILE"
ENV_LOG_MAX_BYTES: Final[str] = "LOG_MAX_BYTES"
ENV_LOG_BACKUP_COUNT: Final[str] = "LOG_BACKUP_COUNT"

ENV_PLUGINS_PACKAGE: Final[str] = "PLUGINS_PACKAGE"
ENV_TIMEZONE: Final[str] = "TIMEZONE"


# ---------------------------------------------------------------------------
# Helper constants
# ---------------------------------------------------------------------------

EMPTY_STRING: Final[str] = ""
UNKNOWN_VALUE: Final[str] = "Unknown"


__all__ = [
    "PROJECT_NAME",
    "PROJECT_SHORT_NAME",
    "PROJECT_VERSION",
    "CORE_PACKAGE",
    "PLUGINS_PACKAGE",
    "DATABASE_PACKAGE",
    "UTILS_PACKAGE",
    "MESSAGES_PACKAGE",
    "KEYBOARDS_PACKAGE",
    "CALLBACK_START",
    "CALLBACK_HELP",
    "CALLBACK_SEARCH",
    "CALLBACK_FILE",
    "CALLBACK_ADMIN",
    "CALLBACK_BACKUP",
    "CALLBACK_PREMIUM",
    "CALLBACK_STATS",
    "CALLBACK_NAV",
    "FILE_CALLBACK_SEPARATOR",
    "FILE_CALLBACK_PREFIX",
    "DEFAULT_PAGE_SIZE",
    "MIN_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "DEFAULT_MAX_SEARCH_RESULTS",
    "MAX_CALLBACK_DATA_LENGTH",
    "DEFAULT_OPERATION_TIMEOUT_SECONDS",
    "DEFAULT_TELEGRAM_TIMEOUT_SECONDS",
    "DEFAULT_RETRY_ATTEMPTS",
    "DEFAULT_RETRY_DELAY_SECONDS",
    "USE_CACHED_TELEGRAM_MEDIA",
    "PRIMARY_MEDIA_IDENTIFIER",
    "PRIMARY_MEDIA_DATABASE",
    "MEDIA_DATABASE_PREFIX",
    "MEDIA_DATABASE_NAMES",
    "LOGGER_ROOT_NAME",
    "ENV_API_ID",
    "ENV_API_HASH",
    "ENV_BOT_TOKEN",
    "ENV_SESSION_NAME",
    "ENV_DATABASE_URL",
    "ENV_MEDIA_DATABASE_URLS",
    "ENV_ADMIN_IDS",
    "ENV_OWNER_IDS",
    "ENV_BACKUP_ENABLED",
    "ENV_BACKUP_CHANNEL_ID",
    "ENV_BACKUP_DELAY",
    "ENV_ENABLE_SEARCH",
    "ENV_SEARCH_PAGE_SIZE",
    "ENV_MAX_SEARCH_RESULTS",
    "ENV_ENABLE_BACKUP",
    "ENV_ENABLE_PREMIUM",
    "ENV_ENABLE_STATISTICS",
    "ENV_LOG_LEVEL",
    "ENV_LOG_TO_FILE",
    "ENV_LOG_DIR",
    "ENV_LOG_FILE",
    "ENV_LOG_MAX_BYTES",
    "ENV_LOG_BACKUP_COUNT",
    "ENV_PLUGINS_PACKAGE",
    "ENV_TIMEZONE",
    "EMPTY_STRING",
    "UNKNOWN_VALUE",
]
