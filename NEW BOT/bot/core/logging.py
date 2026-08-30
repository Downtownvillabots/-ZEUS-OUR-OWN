
bot.core.logging

Centralized logging configuration.

Provides
    - Console logging.
    - File logging.
    - Structured context helpers.
    - Requestuser context.
    - Environment-aware log levels.


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
# Context
# ============================================================================

request_id_context contextvars.ContextVar[
    Optional[str]
] = contextvars.ContextVar(
    request_id,
    default=None,
)

user_id_context contextvars.ContextVar[
    Optional[int]
] = contextvars.ContextVar(
    user_id,
    default=None,
)

chat_id_context contextvars.ContextVar[
    Optional[int]
] = contextvars.ContextVar(
    chat_id,
    default=None,
)


# ============================================================================
# Context helpers
# ============================================================================

def set_request_context(
    ,
    request_id Optional[str] = None,
    user_id Optional[int] = None,
    chat_id Optional[int] = None,
) - None

    request_id_context.set(
        request_id
    )

    user_id_context.set(
        user_id
    )

    chat_id_context.set(
        chat_id
    )


def clear_request_context() - None

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
)

    def filter(
        self,
        record logging.LogRecord,
    ) - bool

        record.request_id = (
            request_id_context.get()
            or -
        )

        record.user_id = (
            user_id_context.get()
            or -
        )

        record.chat_id = (
            chat_id_context.get()
            or -
        )

        return True


# ============================================================================
# Formatter
# ============================================================================

class ContextFormatter(
    logging.Formatter
)

    def format(
        self,
        record logging.LogRecord,
    ) - str

        if not hasattr(
            record,
            request_id,
        )
            record.request_id = -

        if not hasattr(
            record,
            user_id,
        )
            record.user_id = -

        if not hasattr(
            record,
            chat_id,
        )
            record.chat_id = -

        return super().format(
            record
        )


# ============================================================================
# Logger configuration
# ============================================================================

_configured = False


def _level(
    value str,
) - int

    value = str(
        value
    ).upper()

    return getattr(
        logging,
        value,
        logging.INFO,
    )


def configure_logging(
    ,
    level Optional[str] = None,
    log_directory Optional[str] = None,
    log_file Optional[str] = None,
    enable_file bool = True,
    force bool = False,
) - logging.Logger

    global _configured

    root = logging.getLogger()

    if (
        _configured
        and not force
    )
        return root

    if force

        for handler in list(
            root.handlers
        )

            root.removeHandler(
                handler
            )

            try
                handler.close()
            except Exception
                pass

    level_value = (
        level
        or os.getenv(
            LOG_LEVEL,
            DEFAULT_LOG_LEVEL,
        )
    )

    root.setLevel(
        _level(level_value)
    )

    formatter = ContextFormatter(
        fmt=(
            DEFAULT_LOG_FORMAT
            +   request=%(request_id)s
            +   user=%(user_id)s
            +   chat=%(chat_id)s
        ),
        datefmt=DEFAULT_LOG_DATE_FORMAT,
    )

    context_filter = (
        ContextFilter()
    )

    console = logging.StreamHandler(
        sys.stdout
    )

    console.setLevel(
        _level(level_value)
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

    if enable_file

        directory = Path(
            log_directory
            or os.getenv(
                LOG_DIRECTORY,
                logs,
            )
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = Path(
            log_file
            or directory  bot.log
        )

        file_handler = (
            logging.handlers.RotatingFileHandler(
                filename=path,
                maxBytes=10  1024  1024,
                backupCount=5,
                encoding=utf-8,
            )
        )

        file_handler.setLevel(
            _level(level_value)
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

    _configure_library_loggers(
        level_value
    )

    _configured = True

    return root


def _configure_library_loggers(
    level str,
) - None

    noisy = {
        httpx,
        httpcore,
        telegram,
        telegram.ext,
        asyncio,
    }

    for name in noisy

        logging.getLogger(
            name
        ).setLevel(
            _level(level)
        )


def get_logger(
    name Optional[str] = None,
) - logging.Logger

    return logging.getLogger(
        name
    )


def configure_from_environment() - logging.Logger

    return configure_logging(
        level=os.getenv(
            LOG_LEVEL,
            DEFAULT_LOG_LEVEL,
        ),
        log_directory=os.getenv(
            LOG_DIRECTORY,
            logs,
        ),
        enable_file=(
            os.getenv(
                LOG_TO_FILE,
                true,
            ).lower()
            in {
                1,
                true,
                yes,
                on,
            }
        ),
    )


__all__ = [
    request_id_context,
    user_id_context,
    chat_id_context,
    set_request_context,
    clear_request_context,
    ContextFilter,
    ContextFormatter,
    configure_logging,
    configure_from_environment,
    get_logger,
]