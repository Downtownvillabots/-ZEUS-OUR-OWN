"""
DOWNTOWN VILLA
File 5: core/errors.py

Central error definitions and safe error-handling helpers.

Goals:
    - Give the project clear, reusable exception types.
    - Keep feature-specific errors separate from infrastructure errors.
    - Make errors easy to identify in logs.
    - Prevent plugins from creating competing exception systems.
    - Provide a common way to log unexpected exceptions.

Important:
    This module does not decide how Telegram users should see every error.
    User-facing messages belong in the message/feature layer later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.logging import get_logger, log_exception


LOGGER = get_logger(__name__)


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------

class DowntownVillaError(Exception):
    """
    Base exception for expected DOWNTOWN VILLA application errors.

    Feature-specific exceptions should inherit from this class.
    """


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------

class ConfigurationError(DowntownVillaError):
    """Raised when bot configuration is invalid or incomplete."""


# ---------------------------------------------------------------------------
# Telegram errors
# ---------------------------------------------------------------------------

class TelegramError(DowntownVillaError):
    """Base exception for application-level Telegram errors."""


class TelegramClientError(TelegramError):
    """Raised when the Telegram client cannot perform an operation."""


class TelegramPermissionError(TelegramError):
    """Raised when Telegram permissions prevent an operation."""


class TelegramRateLimitError(TelegramError):
    """Raised when an operation is limited by Telegram rate limits."""

    def __init__(
        self,
        message: str = "Telegram rate limit reached.",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Database errors
# ---------------------------------------------------------------------------

class DatabaseError(DowntownVillaError):
    """Base exception for database-related application errors."""


class DatabaseConnectionError(DatabaseError):
    """Raised when a database connection cannot be established."""


class DatabaseQueryError(DatabaseError):
    """Raised when a database query fails."""


class DatabaseDuplicateError(DatabaseError):
    """Raised when an operation would create a duplicate record."""


class DatabaseNotFoundError(DatabaseError):
    """Raised when a required database record does not exist."""


# ---------------------------------------------------------------------------
# Media errors
# ---------------------------------------------------------------------------

class MediaError(DowntownVillaError):
    """Base exception for media-related operations."""


class MediaNotFoundError(MediaError):
    """Raised when requested Telegram media cannot be found."""


class MediaInvalidError(MediaError):
    """Raised when stored media information is invalid."""


class MediaDeliveryError(MediaError):
    """Raised when cached Telegram media cannot be delivered."""


# ---------------------------------------------------------------------------
# Search errors
# ---------------------------------------------------------------------------

class SearchError(DowntownVillaError):
    """Base exception for search-related operations."""


class SearchQueryError(SearchError):
    """Raised when a search query is invalid."""


class SearchUnavailableError(SearchError):
    """Raised when the search service is temporarily unavailable."""


# ---------------------------------------------------------------------------
# Authorization errors
# ---------------------------------------------------------------------------

class AuthorizationError(DowntownVillaError):
    """Base exception for access-control failures."""


class UnauthorizedError(AuthorizationError):
    """Raised when a user is not allowed to perform an operation."""


class AdminRequiredError(AuthorizationError):
    """Raised when an administrator permission is required."""


class OwnerRequiredError(AuthorizationError):
    """Raised when an owner permission is required."""


# ---------------------------------------------------------------------------
# Backup errors
# ---------------------------------------------------------------------------

class BackupError(DowntownVillaError):
    """Base exception for backup operations."""


class BackupConfigurationError(BackupError):
    """Raised when backup settings are missing or invalid."""


class BackupDeliveryError(BackupError):
    """Raised when a backup item cannot be delivered."""


# ---------------------------------------------------------------------------
# Error information
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """
    Safe structured information about an exception.

    This object deliberately does not store secrets or complete Telegram
    credentials. It is intended for logging, diagnostics, and future
    centralized error reporting.
    """

    exception_type: str
    message: str
    expected: bool
    category: str


def classify_error(error: BaseException) -> ErrorInfo:
    """
    Convert an exception into safe structured information.

    Expected application exceptions are categorized by their class.
    Unknown exceptions are treated as unexpected.
    """
    expected = isinstance(error, DowntownVillaError)

    if isinstance(error, ConfigurationError):
        category = "configuration"
    elif isinstance(error, TelegramError):
        category = "telegram"
    elif isinstance(error, DatabaseError):
        category = "database"
    elif isinstance(error, MediaError):
        category = "media"
    elif isinstance(error, SearchError):
        category = "search"
    elif isinstance(error, AuthorizationError):
        category = "authorization"
    elif isinstance(error, BackupError):
        category = "backup"
    else:
        category = "unexpected"

    return ErrorInfo(
        exception_type=type(error).__name__,
        message=str(error) or "No error message provided.",
        expected=expected,
        category=category,
    )


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def report_error(
    error: BaseException,
    *,
    context: str = "",
    logger: Any = LOGGER,
) -> ErrorInfo:
    """
    Log an error consistently and return its structured information.

    Expected application errors are logged at WARNING level.
    Unexpected errors are logged with a full traceback.

    Example:

        try:
            await do_something()
        except Exception as exc:
            report_error(exc, context="media delivery")
    """
    info = classify_error(error)

    prefix = f"{context}: " if context else ""

    if info.expected:
        logger.warning(
            "%s%s [%s]",
            prefix,
            info.message,
            info.category,
        )
    else:
        log_exception(
            logger,
            "%sUnexpected %s: %s [%s]",
            prefix,
            info.exception_type,
            info.message,
            info.category,
        )

    return info


def is_expected_error(error: BaseException) -> bool:
    """Return True when the exception is a known application error."""
    return isinstance(error, DowntownVillaError)


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "DowntownVillaError",
    "ConfigurationError",
    "TelegramError",
    "TelegramClientError",
    "TelegramPermissionError",
    "TelegramRateLimitError",
    "DatabaseError",
    "DatabaseConnectionError",
    "DatabaseQueryError",
    "DatabaseDuplicateError",
    "DatabaseNotFoundError",
    "MediaError",
    "MediaNotFoundError",
    "MediaInvalidError",
    "MediaDeliveryError",
    "SearchError",
    "SearchQueryError",
    "SearchUnavailableError",
    "AuthorizationError",
    "UnauthorizedError",
    "AdminRequiredError",
    "OwnerRequiredError",
    "BackupError",
    "BackupConfigurationError",
    "BackupDeliveryError",
    "ErrorInfo",
    "classify_error",
    "report_error",
    "is_expected_error",
]
