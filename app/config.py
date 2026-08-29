"""
DOWNTOWN VILLA
Central environment configuration.

Do not put secrets in source code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )
    return value


def _int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        if default is None:
            raise RuntimeError(
                f"Missing required environment variable: {name}"
            )
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a valid float.") from exc


def _list(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True, slots=True)
class Config:
    project_name: str
    api_id: int
    api_hash: str
    bot_token: str
    session_name: str
    log_level: str
    port: int

    # Database Configuration
    database_name: str
    database_1_uri: str
    media_database_uris: list[str]
    media_database_rotation_mb: float


_CONFIG: Config | None = None


def get_config() -> Config:
    global _CONFIG

    if _CONFIG is None:
        _CONFIG = Config(
            project_name="DOWNTOWN VILLA",
            api_id=_int("API_ID"),
            api_hash=_required("API_HASH"),
            bot_token=_required("BOT_TOKEN"),
            session_name=(
                os.getenv("SESSION_NAME", "downtown_villa_bot").strip()
                or "downtown_villa_bot"
            ),
            log_level=(
                os.getenv("LOG_LEVEL", "INFO").strip().upper()
                or "INFO"
            ),
            port=_int("PORT", 8080),
            
            # Reads DATABASE_NAME, defaults to Cluster0
            database_name=(
                os.getenv("DATABASE_NAME", "Cluster0").strip()
                or "Cluster0"
            ),
            database_1_uri=_required("DATABASE_1_URI"),
            media_database_uris=_list("MEDIA_DATABASE_URIS"),
            media_database_rotation_mb=_float("MEDIA_DATABASE_ROTATION_MB", 400.0),
        )

    return _CONFIG
