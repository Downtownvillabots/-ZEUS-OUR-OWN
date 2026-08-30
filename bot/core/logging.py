"""
bot.core.logging

Centralized application logging.

Provides:
    - Console logging.
    - Rotating file logging.
    - Request/user/chat context.
    - Environment-aware log levels.
    - Safe structured context fields.
"""

from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


from .constants import (
    DEFAULT_LOG_DATE_FORMAT,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
)


# ============================================================================
# Context variables
# ============================================================================

request_id_context: contextvars.ContextVar[
    Optional[str]
] = contextvars.ContextVar(
    "request_id",
    default=None,
)


user_id_context: contextvars.ContextVar[
    Optional[int]
] = contextvars.ContextVar(
    "user_id",
    default=None,
)


chat_id_context: contextvars.ContextVar[
    Optional[int]
] = contextvars.ContextVar(
    "chat_id",
    default=None,
)


# ============================================================================
# Context helpers
# ============================================================================


def set_request_context(
    request_id: Optional[str] = None,
    user_id: Optional[int] = None,
    chat_id: Optional[int] = None,
) -> None:
    """
    Set contextual values for the current async/task context.
    """

    request_id_context.set(
        request_id
    )

    user_id_context.set(
        user_id
    )

    chat_id_context.set(
        chat_id
    )


def clear_request_context() -> None:
    """
    Clear all contextual logging values.
    """

    request_id_context.set(
        None
    )

    user_id_context.set(
        None
    )

    chat_id_context.set(
        None
    )


# ============================================================================
# Logging filter
# ============================================================================


class ContextFilter(
    logging.Filter
):
    """
    Inject request/user/chat context into LogRecord objects.
    """

    def filter(
        self,
        record: logging.LogRecord,
    ) -> bool:
        """
        Add safe context fields to a log record.
        """

        record.request_id = (
            request_id_context.get()
            or "-"
        )

        record.user_id = (
            user_id_context.get()
            if user_id_context.get() is not None
            else "-"
        )

        record.chat_id = (
            chat_id_context.get()
            if chat_id_context.get() is not None
            else "-"
        )

        return True


# ============================================================================
# Formatter
# ============================================================================


class ContextFormatter(
    logging.Formatter
):
    """
    Formatter that guarantees context fields exist.

    This prevents formatting failures when a third-party library emits a
    record without passing through ContextFilter.
    """

    def format(
        self,
        record: logging.LogRecord,
    ) -> str:
        """
        Format a log record with safe context defaults.
        """

        if not hasattr(
            record,
            "request_id",
        ):
            record.request_id = "-"

        if not hasattr(
            record,
            "user_id",
        ):
            record.user_id = "-"

        if not hasattr(
            record,
            "chat_id",
        ):
            record.chat_id = "-"

        return super().format(
            record
        )


# ============================================================================
# Configuration state
# ============================================================================


_configured = False


# ============================================================================
# Log level helpers
# ============================================================================


def _level(
    value: str,
) -> int:
    """
    Convert a textual log level to a logging constant.
    """

    normalized = str(
        value
    ).strip().upper()

    return getattr(
        logging,
        normalized,
        logging.INFO,
    )


def _env_bool(
    value: str,
    default: bool = True,
) -> bool:
    """
    Convert an environment value to a boolean.
    """

    if value is None:
        return default

    normalized = str(
        value
    ).strip().lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "n",
        "off",
    }:
        return False

    return default


# ============================================================================
# Logger configuration
# ============================================================================


def configure_logging(
    *,
    level: Optional[str] = None,
    log_directory: Optional[str] = None,
    log_file: Optional[str] = None,
    enable_file: bool = True,
    force: bool = False,
) -> logging.Logger:
    """
    Configure application-wide logging.

    Configuration is idempotent unless ``force=True`` is supplied.
    """

    global _configured

    root = logging.getLogger()

    if (
        _configured
        and not force
    ):
        return root

    # ------------------------------------------------------------------------
    # Remove previous handlers when explicitly forcing configuration.
    # ------------------------------------------------------------------------

    if force:

        for handler in list(
            root.handlers
        ):

            root.removeHandler(
                handler
            )

            try:
                handler.close()

            except Exception:
                pass

    # ------------------------------------------------------------------------
    # Resolve configuration.
    # ------------------------------------------------------------------------

    level_value = (
        level
        or os.getenv(
            "LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        )
    )

    numeric_level = _level(
        level_value
    )

    root.setLevel(
        numeric_level
    )

    # ------------------------------------------------------------------------
    # Formatter.
    # ------------------------------------------------------------------------

    formatter = ContextFormatter(
        fmt=(
            DEFAULT_LOG_FORMAT
            + " request=%(request_id)s"
            + " user=%(user_id)s"
            + " chat=%(chat_id)s"
        ),
        datefmt=(
            DEFAULT_LOG_DATE_FORMAT
        ),
    )

    context_filter = ContextFilter()

    # ------------------------------------------------------------------------
    # Console handler.
    # ------------------------------------------------------------------------

    console = logging.StreamHandler(
        sys.stdout
    )

    console.setLevel(
        numeric_level
    )

    console.setFormatter(
        formatter
    )

    console.addFilter(
        context_filter
    )

    root.addHandler(
        console
    )

    # ------------------------------------------------------------------------
    # File handler.
    # ------------------------------------------------------------------------

    if enable_file:

        directory = Path(
            log_directory
            or os.getenv(
                "LOG_DIRECTORY",
                "logs",
            )
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = Path(
            log_file
            or (
                directory
                / "bot.log"
            )
        )

        file_handler = (
            logging.handlers.RotatingFileHandler(
                filename=path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )

        file_handler.setLevel(
            numeric_level
        )

        file_handler.setFormatter(
            formatter
        )

        file_handler.addFilter(
            context_filter
        )

        root.addHandler(
            file_handler
        )

    # ------------------------------------------------------------------------
    # Third-party logger configuration.
    # ------------------------------------------------------------------------

    _configure_library_loggers(
        level_value
    )

    _configured = True

    return root


# ============================================================================
# Third-party logger configuration
# ============================================================================


def _configure_library_loggers(
    level: str,
) -> None:
    """
    Configure noisy dependency loggers.

    The project uses Pyrogram, so Pyrogram logging is included here.
    """

    numeric_level = _level(
        level
    )

    noisy = {
        "httpx",
        "httpcore",
        "telegram",
        "telegram.ext",
        "pyrogram",
        "asyncio",
    }

    for name in noisy:

        logging.getLogger(
            name
        ).setLevel(
            numeric_level
        )


# ============================================================================
# Logger accessor
# ============================================================================


def get_logger(
    name: Optional[str] = None,
) -> logging.Logger:
    """
    Return a standard library logger.
    """

    return logging.getLogger(
        name
    )


# ============================================================================
# Environment configuration
# ============================================================================


def configure_from_environment() -> logging.Logger:
    """
    Configure logging from environment variables.
    """

    return configure_logging(
        level=os.getenv(
            "LOG_LEVEL",
            DEFAULT_LOG_LEVEL,
        ),
        log_directory=os.getenv(
            "LOG_DIRECTORY",
            "logs",
        ),
        log_file=os.getenv(
            "LOG_FILE",
            "logs/bot.log",
        ),
        enable_file=_env_bool(
            os.getenv(
                "LOG_TO_FILE",
                "true",
            ),
            default=True,
        ),
    )


# ============================================================================
# Public API
# ============================================================================


__all__ = [
    "request_id_context",
    "user_id_context",
    "chat_id_context",
    "set_request_context",
    "clear_request_context",
    "ContextFilter",
    "ContextFormatter",
    "configure_logging",
    "configure_from_environment",
    "get_logger",
]
```
