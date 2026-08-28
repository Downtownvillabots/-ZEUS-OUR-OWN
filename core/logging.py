"""
DOWNTOWN VILLA
File 3: core/logging.py

Centralized logging for the entire bot.

Goals:
    - One consistent logging system for every module.
    - Easy log-level changes through configuration.
    - Human-readable console logs.
    - Optional rotating file logs.
    - No feature-specific logging logic.
    - Safe handling of unexpected exceptions.

Feature modules should use:

    from core.logging import get_logger

    LOGGER = get_logger(__name__)

Do not create separate logging.basicConfig() calls inside plugins.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Final


PROJECT_NAME: Final[str] = "DOWNTOWN VILLA"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOG_DIR: Final[str] = "logs"
DEFAULT_LOG_FILE: Final[str] = "downtown_villa.log"
DEFAULT_MAX_BYTES: Final[int] = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT: Final[int] = 5

_LOGGER_NAME: Final[str] = "downtown_villa"
_CONFIGURED: bool = False


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    """Read and trim an environment variable."""
    return os.getenv(name, default).strip()


def _positive_int(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
    raw = _env(name)

    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable '{name}' must be an integer."
        ) from exc

    if value <= 0:
        raise RuntimeError(
            f"Environment variable '{name}' must be greater than zero."
        )

    return value


def _resolve_level(value: str) -> int:
    """Convert a log-level name into a logging module constant."""
    normalized = value.strip().upper() or DEFAULT_LOG_LEVEL
    level = getattr(logging, normalized, None)

    if not isinstance(level, int):
        raise RuntimeError(
            f"Invalid LOG_LEVEL '{value}'. "
            "Use DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )

    return level


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

class DowntownVillaFormatter(logging.Formatter):
    """
    Consistent formatter for DOWNTOWN VILLA logs.

    Example:
        2026-08-28 14:30:00 | INFO     | plugins.start | Bot started
    """

    def __init__(self) -> None:
        super().__init__(
            fmt=(
                "%(asctime)s | %(levelname)-8s | "
                "%(name)s | %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )


# ---------------------------------------------------------------------------
# Handler creation
# ---------------------------------------------------------------------------

def _create_console_handler(level: int) -> logging.Handler:
    """Create the standard stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(DowntownVillaFormatter())
    return handler


def _create_file_handler(
    log_dir: Path,
    level: int,
) -> logging.Handler | None:
    """
    Create a rotating file handler.

    File logging can be disabled with:
        LOG_TO_FILE=false
    """
    enabled = _env("LOG_TO_FILE", "true").lower()

    if enabled in {"0", "false", "no", "off", "disabled"}:
        return None

    log_dir.mkdir(parents=True, exist_ok=True)

    file_name = (
        _env("LOG_FILE", DEFAULT_LOG_FILE)
        or DEFAULT_LOG_FILE
    )

    max_bytes = _positive_int(
        "LOG_MAX_BYTES",
        DEFAULT_MAX_BYTES,
    )

    backup_count = _positive_int(
        "LOG_BACKUP_COUNT",
        DEFAULT_BACKUP_COUNT,
    )

    log_path = log_dir / file_name

    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )

    handler.setLevel(level)
    handler.setFormatter(DowntownVillaFormatter())

    return handler


# ---------------------------------------------------------------------------
# Central configuration
# ---------------------------------------------------------------------------

def configure_logging() -> logging.Logger:
    """
    Configure the root DOWNTOWN VILLA logger once.

    Calling this function repeatedly is safe; existing handlers are reused.
    """
    global _CONFIGURED

    root_logger = logging.getLogger(_LOGGER_NAME)

    if _CONFIGURED:
        return root_logger

    level_name = _env("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    level = _resolve_level(level_name)

    root_logger.setLevel(level)
    root_logger.propagate = False

    # Avoid duplicate handlers when a development server reloads modules.
    if not root_logger.handlers:
        console_handler = _create_console_handler(level)
        root_logger.addHandler(console_handler)

        log_dir = Path(
            _env("LOG_DIR", DEFAULT_LOG_DIR)
            or DEFAULT_LOG_DIR
        )

        file_handler = _create_file_handler(log_dir, level)

        if file_handler is not None:
            root_logger.addHandler(file_handler)

    _CONFIGURED = True

    root_logger.info(
        "%s logging initialized | level=%s",
        PROJECT_NAME,
        logging.getLevelName(level),
    )

    return root_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return a child logger belonging to DOWNTOWN VILLA.

    Examples:
        get_logger()
        get_logger(__name__)
        get_logger("database.media")
    """
    configure_logging()

    if not name:
        return logging.getLogger(_LOGGER_NAME)

    if name == _LOGGER_NAME or name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)

    # Convert normal module names into the project namespace.
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


# ---------------------------------------------------------------------------
# Runtime controls
# ---------------------------------------------------------------------------

def set_log_level(level: str | int) -> None:
    """
    Change the logging level at runtime.

    This is intentionally centralized so an admin/configuration system can
    later change logging without every module knowing about handlers.
    """
    configure_logging()

    if isinstance(level, str):
        resolved_level = _resolve_level(level)
    elif isinstance(level, int):
        resolved_level = level
    else:
        raise TypeError("Log level must be a string or integer.")

    root_logger = logging.getLogger(_LOGGER_NAME)
    root_logger.setLevel(resolved_level)

    for handler in root_logger.handlers:
        handler.setLevel(resolved_level)

    root_logger.info(
        "DOWNTOWN VILLA log level changed to %s.",
        logging.getLevelName(resolved_level),
    )


def get_log_level() -> str:
    """Return the current DOWNTOWN VILLA log level name."""
    configure_logging()
    return logging.getLevelName(
        logging.getLogger(_LOGGER_NAME).level
    )


# ---------------------------------------------------------------------------
# Exception helpers
# ---------------------------------------------------------------------------

def log_exception(
    logger: logging.Logger,
    message: str,
    *args: object,
) -> None:
    """
    Log an exception with a traceback.

    Use this inside an except block:

        try:
            ...
        except Exception:
            log_exception(LOGGER, "Search failed")
    """
    logger.error(
        message,
        *args,
        exc_info=True,
    )


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def shutdown_logging() -> None:
    """
    Flush and close project logging handlers.

    The function is safe to call more than once.
    """
    global _CONFIGURED

    logger = logging.getLogger(_LOGGER_NAME)

    for handler in list(logger.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            logger.removeHandler(handler)

    _CONFIGURED = False


# Configure logging when this module is imported so every future feature
# immediately receives the same logging behavior.
LOGGER = configure_logging()


__all__ = [
    "PROJECT_NAME",
    "DowntownVillaFormatter",
    "configure_logging",
    "get_logger",
    "set_log_level",
    "get_log_level",
    "log_exception",
    "shutdown_logging",
    "LOGGER",
]
