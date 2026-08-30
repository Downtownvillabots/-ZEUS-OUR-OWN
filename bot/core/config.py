"""
bot.core.config

Central application configuration.

Configuration is loaded from environment variables and converted
into strongly typed Python objects.

Design goals:
    - No secrets hardcoded in source.
    - Safe defaults for local development.
    - Explicit validation for production.
    - Centralized configuration access.
    - Immutable configuration after construction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .constants import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_LANGUAGE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TIMEZONE,
    DEFAULT_WRITE_TIMEOUT_SECONDS,
    DB_COMMAND_TIMEOUT_SECONDS,
    DB_CONNECTION_TIMEOUT_SECONDS,
    DB_POOL_MAX_SIZE,
    DB_POOL_MIN_SIZE,
    ENV_ADMIN_IDS,
    ENV_BOT_TOKEN,
    ENV_DATABASE_URL,
    ENV_DEBUG,
    ENV_ENCRYPTION_KEY,
    ENV_ENVIRONMENT,
    ENV_LOG_LEVEL,
    ENV_MOVIE_API_KEY,
    ENV_REDIS_URL,
    ENV_SECRET_KEY,
    ENV_SHORTENER_API_KEY,
    ENV_STORAGE_ACCESS_KEY,
    ENV_STORAGE_BUCKET,
    ENV_STORAGE_ENDPOINT,
    ENV_STORAGE_SECRET_KEY,
    ENV_TIMEZONE,
    ENV_WEBHOOK_PATH,
    ENV_WEBHOOK_PORT,
    ENV_WEBHOOK_SECRET,
    ENV_WEBHOOK_URL,
    ENV_PRODUCTION,
    MAX_PAGE_SIZE,
    VALID_ENVIRONMENTS,
)


# ============================================================================
# Helpers
# ============================================================================

def _env(
    name: str,
    default: Optional[str] = None,
) -> Optional[str]:

    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip()

    if not value:
        return default

    return value


def _bool(
    name: str,
    default: bool = False,
) -> bool:

    value = _env(name)

    if value is None:
        return default

    return value.lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "enabled",
    }


def _int(
    name: str,
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    value = _env(name)

    if value is None:
        result = default
    else:
        try:
            result = int(value)
        except ValueError as exc:
            raise ValueError(
                f"{name} must be an integer."
            ) from exc

    if minimum is not None and result < minimum:
        raise ValueError(
            f"{name} must be >= {minimum}."
        )

    if maximum is not None and result > maximum:
        raise ValueError(
            f"{name} must be <= {maximum}."
        )

    return result


def _float(
    name: str,
    default: float,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:

    value = _env(name)

    if value is None:
        result = default
    else:
        try:
            result = float(value)
        except ValueError as exc:
            raise ValueError(
                f"{name} must be a number."
            ) from exc

    if minimum is not None and result < minimum:
        raise ValueError(
            f"{name} must be >= {minimum}."
        )

    if maximum is not None and result > maximum:
        raise ValueError(
            f"{name} must be <= {maximum}."
        )

    return result


def _csv(
    name: str,
) -> tuple[str, ...]:

    value = _env(name)

    if not value:
        return ()

    return tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )


def _admin_ids() -> frozenset[int]:

    values = _csv(ENV_ADMIN_IDS)

    result: set[int] = set()

    for value in values:

        try:
            result.add(int(value))
        except ValueError as exc:
            raise ValueError(
                f"{ENV_ADMIN_IDS} contains invalid ID: {value}"
            ) from exc

    return frozenset(result)


# ============================================================================
# Database configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class DatabaseConfig:

    url: str = ""

    pool_min_size: int = DB_POOL_MIN_SIZE

    pool_max_size: int = DB_POOL_MAX_SIZE

    connection_timeout: int = (
        DB_CONNECTION_TIMEOUT_SECONDS
    )

    command_timeout: int = (
        DB_COMMAND_TIMEOUT_SECONDS
    )

    echo: bool = False

    @classmethod
    def from_env(
        cls,
    ) -> "DatabaseConfig":

        return cls(
            url=_env(
                ENV_DATABASE_URL,
                "",
            ) or "",
            pool_min_size=_int(
                "DB_POOL_MIN_SIZE",
                DB_POOL_MIN_SIZE,
                minimum=1,
            ),
            pool_max_size=_int(
                "DB_POOL_MAX_SIZE",
                DB_POOL_MAX_SIZE,
                minimum=1,
            ),
            connection_timeout=_int(
                "DB_CONNECTION_TIMEOUT",
                DB_CONNECTION_TIMEOUT_SECONDS,
                minimum=1,
            ),
            command_timeout=_int(
                "DB_COMMAND_TIMEOUT",
                DB_COMMAND_TIMEOUT_SECONDS,
                minimum=1,
            ),
            echo=_bool(
                "DB_ECHO",
                False,
            ),
        )

    def validate(
        self,
        *,
        production: bool = False,
    ) -> list[str]:

        errors: list[str] = []

        if production and not self.url:
            errors.append(
                "DATABASE_URL is required in production."
            )

        if self.pool_min_size > self.pool_max_size:
            errors.append(
                "Database pool minimum cannot exceed maximum."
            )

        return errors


# ============================================================================
# Redis configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class RedisConfig:

    url: str = ""

    max_connections: int = 50

    connect_timeout: float = 5.0

    socket_timeout: float = 5.0

    enabled: bool = True

    @classmethod
    def from_env(
        cls,
    ) -> "RedisConfig":

        url = _env(
            ENV_REDIS_URL,
            "",
        ) or ""

        return cls(
            url=url,
            max_connections=_int(
                "REDIS_MAX_CONNECTIONS",
                50,
                minimum=1,
            ),
            connect_timeout=_float(
                "REDIS_CONNECT_TIMEOUT",
                5.0,
                minimum=0.1,
            ),
            socket_timeout=_float(
                "REDIS_SOCKET_TIMEOUT",
                5.0,
                minimum=0.1,
            ),
            enabled=_bool(
                "REDIS_ENABLED",
                bool(url),
            ),
        )

    def validate(
        self,
        *,
        production: bool = False,
    ) -> list[str]:

        errors: list[str] = []

        if production and self.enabled and not self.url:
            errors.append(
                "REDIS_URL is required when Redis is enabled."
            )

        return errors


# ============================================================================
# Telegram configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class TelegramConfig:

    bot_token: str = ""

    api_id: Optional[int] = None

    api_hash: Optional[str] = None

    webhook_url: Optional[str] = None

    webhook_secret: Optional[str] = None

    webhook_path: str = "/telegram/webhook"

    webhook_port: int = 8080

    drop_pending_updates: bool = True

    allowed_updates: tuple[str, ...] = ()

    @classmethod
    def from_env(
        cls,
    ) -> "TelegramConfig":

        api_id_value = _env(
            "TELEGRAM_API_ID"
        )

        api_id = None

        if api_id_value:
            try:
                api_id = int(
                    api_id_value
                )
            except ValueError as exc:
                raise ValueError(
                    "TELEGRAM_API_ID must be an integer."
                ) from exc

        return cls(
            bot_token=_env(
                ENV_BOT_TOKEN,
                "",
            ) or "",
            api_id=api_id,
            api_hash=_env(
                "TELEGRAM_API_HASH"
            ),
            webhook_url=_env(
                ENV_WEBHOOK_URL
            ),
            webhook_secret=_env(
                ENV_WEBHOOK_SECRET
            ),
            webhook_path=_env(
                ENV_WEBHOOK_PATH,
                "/telegram/webhook",
            ) or "/telegram/webhook",
            webhook_port=_int(
                ENV_WEBHOOK_PORT,
                8080,
                minimum=1,
                maximum=65535,
            ),
            drop_pending_updates=_bool(
                "TELEGRAM_DROP_PENDING_UPDATES",
                True,
            ),
            allowed_updates=_csv(
                "TELEGRAM_ALLOWED_UPDATES"
            ),
        )

    def validate(
        self,
        *,
        production: bool = False,
    ) -> list[str]:

        errors: list[str] = []

        if not self.bot_token:
            errors.append(
                "BOT_TOKEN is required."
            )

        if production and self.webhook_url:
            if not self.webhook_secret:
                errors.append(
                    "WEBHOOK_SECRET is recommended when using a production webhook."
                )

        if not self.webhook_path.startswith("/"):
            errors.append(
                "WEBHOOK_PATH must start with '/'."
            )

        return errors


# ============================================================================
# Application configuration
# ============================================================================

@dataclass(frozen=True, slots=True)
class AppConfig:

    environment: str = "development"

    debug: bool = False

    timezone: str = DEFAULT_TIMEZONE

    language: str = DEFAULT_LANGUAGE

    page_size: int = DEFAULT_PAGE_SIZE

    request_timeout: int = (
        DEFAULT_REQUEST_TIMEOUT_SECONDS
    )

    connect_timeout: int = (
        DEFAULT_CONNECT_TIMEOUT_SECONDS
    )

    write_timeout: int = (
        DEFAULT_WRITE_TIMEOUT_SECONDS
    )

    cache_ttl: int = (
        DEFAULT_CACHE_TTL_SECONDS
    )

    secret_key: str = ""

    encryption_key: Optional[str] = None

    shortener_api_key: Optional[str] = None

    movie_api_key: Optional[str] = None

    storage_bucket: Optional[str] = None

    storage_endpoint: Optional[str] = None

    storage_access_key: Optional[str] = None

    storage_secret_key: Optional[str] = None

    admin_ids: frozenset[int] = field(
        default_factory=frozenset
    )

    features: Mapping[str, bool] = field(
        default_factory=dict
    )

    @classmethod
    def from_env(
        cls,
    ) -> "AppConfig":

        environment = (
            _env(
                ENV_ENVIRONMENT,
                "development",
            )
            or "development"
        ).lower()

        if environment not in VALID_ENVIRONMENTS:
            raise ValueError(
                f"Unsupported BOT_ENV: {environment}"
            )

        return cls(
            environment=environment,
            debug=_bool(
                ENV_DEBUG,
                environment != ENV_PRODUCTION,
            ),
            timezone=_env(
                ENV_TIMEZONE,
                DEFAULT_TIMEZONE,
            ) or DEFAULT_TIMEZONE,
            language=_env(
                "DEFAULT_LANGUAGE",
                DEFAULT_LANGUAGE,
            ) or DEFAULT_LANGUAGE,
            page_size=_int(
                "PAGE_SIZE",
                DEFAULT_PAGE_SIZE,
                minimum=1,
                maximum=MAX_PAGE_SIZE,
            ),
            request_timeout=_int(
                "REQUEST_TIMEOUT",
                DEFAULT_REQUEST_TIMEOUT_SECONDS,
                minimum=1,
            ),
            connect_timeout=_int(
                "CONNECT_TIMEOUT",
                DEFAULT_CONNECT_TIMEOUT_SECONDS,
                minimum=1,
            ),
            write_timeout=_int(
                "WRITE_TIMEOUT",
                DEFAULT_WRITE_TIMEOUT_SECONDS,
                minimum=1,
            ),
            cache_ttl=_int(
                "CACHE_TTL",
                DEFAULT_CACHE_TTL_SECONDS,
                minimum=0,
            ),
            secret_key=_env(
                ENV_SECRET_KEY,
                "",
            ) or "",
            encryption_key=_env(
                ENV_ENCRYPTION_KEY
            ),
            shortener_api_key=_env(
                ENV_SHORTENER_API_KEY
            ),
            movie_api_key=_env(
                ENV_MOVIE_API_KEY
            ),
            storage_bucket=_env(
                ENV_STORAGE_BUCKET
            ),
            storage_endpoint=_env(
                ENV_STORAGE_ENDPOINT
            ),
            storage_access_key=_env(
                ENV_STORAGE_ACCESS_KEY
            ),
            storage_secret_key=_env(
                ENV_STORAGE_SECRET_KEY
            ),
            admin_ids=_admin_ids(),
            features=_load_features(),
        )

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"

    @property
    def is_staging(self) -> bool:
        return self.environment == "staging"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def feature_enabled(
        self,
        feature: str,
    ) -> bool:

        return bool(
            self.features.get(
                feature,
                False,
            )
        )

    def validate(
        self,
        *,
        raise_on_error: bool = True,
    ) -> list[str]:

        errors: list[str] = []

        production = self.is_production

        if production and not self.secret_key:
            errors.append(
                "SECRET_KEY is required in production."
            )

        if self.page_size < 1:
            errors.append(
                "PAGE_SIZE must be greater than zero."
            )

        if self.page_size > MAX_PAGE_SIZE:
            errors.append(
                f"PAGE_SIZE cannot exceed {MAX_PAGE_SIZE}."
            )

        if self.timezone.strip() == "":
            errors.append(
                "TIMEZONE cannot be empty."
            )

        if raise_on_error and errors:
            raise ConfigurationError(
                "; ".join(errors)
            )

        return errors


# ============================================================================
# Complete settings object
# ============================================================================

@dataclass(frozen=True, slots=True)
class Settings:

    app: AppConfig

    telegram: TelegramConfig

    database: DatabaseConfig

    redis: RedisConfig

    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(
        cls,
    ) -> "Settings":

        settings = cls(
            app=AppConfig.from_env(),
            telegram=TelegramConfig.from_env(),
            database=DatabaseConfig.from_env(),
            redis=RedisConfig.from_env(),
            log_level=(
                _env(
                    ENV_LOG_LEVEL,
                    DEFAULT_LOG_LEVEL,
                )
                or DEFAULT_LOG_LEVEL
            ).upper(),
        )

        settings.validate()

        return settings

    @property
    def environment(self) -> str:
        return self.app.environment

    @property
    def is_production(self) -> bool:
        return self.app.is_production

    def validate(
        self,
        *,
        raise_on_error: bool = True,
    ) -> list[str]:

        errors: list[str] = []

        errors.extend(
            self.app.validate(
                raise_on_error=False
            )
        )

        errors.extend(
            self.telegram.validate(
                production=self.is_production
            )
        )

        errors.extend(
            self.database.validate(
                production=self.is_production
            )
        )

        errors.extend(
            self.redis.validate(
                production=self.is_production
            )
        )

        if raise_on_error and errors:
            raise ConfigurationError(
                "\n".join(
                    f"- {error}"
                    for error in errors
                )
            )

        return errors


# ============================================================================
# Feature loading
# ============================================================================

def _load_features() -> dict[str, bool]:

    features = {
        "search": _bool(
            "FEATURE_SEARCH",
            True,
        ),
        "movies": _bool(
            "FEATURE_MOVIES",
            True,
        ),
        "file_delivery": _bool(
            "FEATURE_FILE_DELIVERY",
            True,
        ),
        "premium": _bool(
            "FEATURE_PREMIUM",
            True,
        ),
        "verification": _bool(
            "FEATURE_VERIFICATION",
            True,
        ),
        "broadcast": _bool(
            "FEATURE_BROADCAST",
            True,
        ),
        "moderation": _bool(
            "FEATURE_MODERATION",
            True,
        ),
        "shortener": _bool(
            "FEATURE_SHORTENER",
            True,
        ),
        "indexer": _bool(
            "FEATURE_INDEXER",
            True,
        ),
    }

    return features


# ============================================================================
# Configuration error
# ============================================================================

class ConfigurationError(
    RuntimeError
):
    """Raised when application configuration is invalid."""


# ============================================================================
# Singleton-style access
# ============================================================================

_settings: Optional[Settings] = None


def load_settings(
    *,
    force_reload: bool = False,
) -> Settings:

    global _settings

    if (
        _settings is None
        or force_reload
    ):

        _settings = (
            Settings.from_env()
        )

    return _settings


def get_settings() -> Settings:

    return load_settings()


def reset_settings() -> None:

    global _settings

    _settings = None


# ============================================================================
# Public helpers
# ============================================================================

def get_admin_ids() -> frozenset[int]:

    return get_settings().app.admin_ids


def is_feature_enabled(
    feature: str,
) -> bool:

    return get_settings().app.feature_enabled(
        feature
    )


def is_production() -> bool:

    return get_settings().app.is_production


def is_development() -> bool:

    return get_settings().app.is_development


def validate_environment() -> list[str]:

    settings = get_settings()

    return settings.validate(
        raise_on_error=False
    )


__all__ = [
    "ConfigurationError",
    "DatabaseConfig",
    "RedisConfig",
    "TelegramConfig",
    "AppConfig",
    "Settings",
    "load_settings",
    "get_settings",
    "reset_settings",
    "get_admin_ids",
    "is_feature_enabled",
    "is_production",
    "is_development",
    "validate_environment",
]