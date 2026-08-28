"""
DOWNTOWN VILLA
File 2: config.py

Central configuration for the new Telegram bot.

Secrets are read from environment variables and are never hardcoded here.
Feature modules should import configuration from this file instead of
reading environment variables independently.

Required:
    API_ID
    API_HASH
    BOT_TOKEN

Optional:
    SESSION_NAME
    LOG_LEVEL
    PLUGINS_PACKAGE
    DATABASE_URL
    MEDIA_DATABASE_URLS
    ADMIN_IDS
    OWNER_IDS
    BACKUP_CHANNEL_ID
    BACKUP_ENABLED
    BACKUP_DELAY
    SEARCH_PAGE_SIZE
    MAX_SEARCH_RESULTS
    ENABLE_SEARCH
    ENABLE_BACKUP
    ENABLE_PREMIUM
    ENABLE_STATISTICS
    TIMEZONE
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final


PROJECT_NAME: Final[str] = "DOWNTOWN VILLA"
PROJECT_VERSION: Final[str] = "0.1.0"


# ---------------------------------------------------------------------------
# Environment parsing helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    """Return a trimmed environment value."""
    return os.getenv(name, default).strip()


def _required(name: str) -> str:
    """Return a required environment value or raise a clear error."""
    value = _env(name)

    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not configured."
        )

    return value


def _int(name: str, default: int | None = None) -> int:
    """Read an integer environment value."""
    raw = _env(name)

    if not raw:
        if default is not None:
            return default
        raise RuntimeError(
            f"Required environment variable '{name}' is not configured."
        )

    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable '{name}' must be an integer."
        ) from exc


def _positive_int(name: str, default: int | None = None) -> int:
    """Read an integer that must be greater than zero."""
    value = _int(name, default)

    if value <= 0:
        raise RuntimeError(
            f"Environment variable '{name}' must be greater than zero."
        )

    return value


def _float(name: str, default: float | None = None) -> float:
    """Read a floating-point environment value."""
    raw = _env(name)

    if not raw:
        if default is not None:
            return default
        raise RuntimeError(
            f"Required environment variable '{name}' is not configured."
        )

    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable '{name}' must be a number."
        ) from exc


def _bool(name: str, default: bool = False) -> bool:
    """Read a human-friendly boolean environment value."""
    raw = _env(name).lower()

    if not raw:
        return default

    if raw in {"1", "true", "yes", "y", "on", "enabled"}:
        return True

    if raw in {"0", "false", "no", "n", "off", "disabled"}:
        return False

    raise RuntimeError(
        f"Environment variable '{name}' must be a boolean "
        "(true/false, yes/no, 1/0, on/off)."
    )


def _id_list(name: str) -> tuple[int, ...]:
    """
    Read comma/space/semicolon separated integer IDs.

    Example:
        ADMIN_IDS=12345,67890
    """
    raw = _env(name)

    if not raw:
        return ()

    normalized = raw.replace(";", ",").replace(" ", ",")

    values: list[int] = []

    for item in normalized.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            value = int(item)
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable '{name}' contains an invalid ID: "
                f"{item!r}."
            ) from exc

        if value not in values:
            values.append(value)

    return tuple(values)


def _string_list(name: str) -> tuple[str, ...]:
    """Read comma/semicolon separated strings."""
    raw = _env(name)

    if not raw:
        return ()

    values: list[str] = []

    for item in raw.replace(";", ",").split(","):
        item = item.strip()

        if item and item not in values:
            values.append(item)

    return tuple(values)


# ---------------------------------------------------------------------------
# Telegram configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    bot_token: str
    session_name: str


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    primary_url: str
    media_urls: tuple[str, ...]


# ---------------------------------------------------------------------------
# Access-control configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AccessConfig:
    admin_ids: tuple[int, ...]
    owner_ids: tuple[int, ...]


# ---------------------------------------------------------------------------
# Backup configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BackupConfig:
    enabled: bool
    channel_id: int | None
    delay_seconds: float


# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SearchConfig:
    enabled: bool
    page_size: int
    max_results: int


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FeatureConfig:
    search: bool
    backup: bool
    premium: bool
    statistics: bool


# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AppConfig:
    project_name: str
    version: str
    log_level: str
    plugins_package: str
    timezone: str
    telegram: TelegramConfig
    database: DatabaseConfig
    access: AccessConfig
    backup: BackupConfig
    search: SearchConfig
    features: FeatureConfig


def load_config() -> AppConfig:
    """
    Build the complete DOWNTOWN VILLA configuration.

    This function performs validation once during startup so feature
    modules can rely on a consistent immutable configuration object.
    """

    api_id = _positive_int("API_ID")

    telegram = TelegramConfig(
        api_id=api_id,
        api_hash=_required("API_HASH"),
        bot_token=_required("BOT_TOKEN"),
        session_name=(
            _env("SESSION_NAME", "downtown_villa_bot")
            or "downtown_villa_bot"
        ),
    )

    primary_database_url = _env("DATABASE_URL")

    database = DatabaseConfig(
        primary_url=primary_database_url,
        media_urls=_string_list("MEDIA_DATABASE_URLS"),
    )

    access = AccessConfig(
        admin_ids=_id_list("ADMIN_IDS"),
        owner_ids=_id_list("OWNER_IDS"),
    )

    backup_channel_raw = _env("BACKUP_CHANNEL_ID")
    backup_channel_id: int | None = None

    if backup_channel_raw:
        try:
            backup_channel_id = int(backup_channel_raw)
        except ValueError as exc:
            raise RuntimeError(
                "Environment variable 'BACKUP_CHANNEL_ID' must be an integer."
            ) from exc

    backup = BackupConfig(
        enabled=_bool("BACKUP_ENABLED", False),
        channel_id=backup_channel_id,
        delay_seconds=_float("BACKUP_DELAY", 0.0),
    )

    search = SearchConfig(
        enabled=_bool("ENABLE_SEARCH", True),
        page_size=_positive_int("SEARCH_PAGE_SIZE", 10),
        max_results=_positive_int("MAX_SEARCH_RESULTS", 100),
    )

    features = FeatureConfig(
        search=_bool("ENABLE_SEARCH", True),
        backup=_bool("ENABLE_BACKUP", False),
        premium=_bool("ENABLE_PREMIUM", False),
        statistics=_bool("ENABLE_STATISTICS", True),
    )

    config = AppConfig(
        project_name=PROJECT_NAME,
        version=PROJECT_VERSION,
        log_level=_env("LOG_LEVEL", "INFO").upper() or "INFO",
        plugins_package=(
            _env("PLUGINS_PACKAGE", "plugins")
            or "plugins"
        ),
        timezone=_env("TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata",
        telegram=telegram,
        database=database,
        access=access,
        backup=backup,
        search=search,
        features=features,
    )

    _validate_config(config)

    return config


def _validate_config(config: AppConfig) -> None:
    """Validate cross-setting relationships."""
    if config.backup.enabled and not config.backup.channel_id:
        raise RuntimeError(
            "BACKUP_ENABLED is enabled but BACKUP_CHANNEL_ID is missing."
        )

    if config.backup.delay_seconds < 0:
        raise RuntimeError(
            "BACKUP_DELAY cannot be negative."
        )

    if config.search.max_results < config.search.page_size:
        raise RuntimeError(
            "MAX_SEARCH_RESULTS must be greater than or equal to "
            "SEARCH_PAGE_SIZE."
        )

    if config.features.backup and not config.backup.enabled:
        raise RuntimeError(
            "ENABLE_BACKUP is enabled but BACKUP_ENABLED is false. "
            "Enable both settings when the backup feature is activated."
        )


# ---------------------------------------------------------------------------
# Public immutable configuration
# ---------------------------------------------------------------------------

CONFIG = load_config()


# Convenient aliases for small/common settings.
# Feature modules that need many settings should use CONFIG directly.

BOT_TOKEN = CONFIG.telegram.bot_token
API_ID = CONFIG.telegram.api_id
API_HASH = CONFIG.telegram.api_hash

ADMIN_IDS = CONFIG.access.admin_ids
OWNER_IDS = CONFIG.access.owner_ids

TIMEZONE = CONFIG.timezone

__all__ = [
    "PROJECT_NAME",
    "PROJECT_VERSION",
    "TelegramConfig",
    "DatabaseConfig",
    "AccessConfig",
    "BackupConfig",
    "SearchConfig",
    "FeatureConfig",
    "AppConfig",
    "load_config",
    "CONFIG",
    "BOT_TOKEN",
    "API_ID",
    "API_HASH",
    "ADMIN_IDS",
    "OWNER_IDS",
    "TIMEZONE",
]
