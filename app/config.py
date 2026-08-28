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


@dataclass(frozen=True, slots=True)
class Config:
    project_name: str
    api_id: int
    api_hash: str
    bot_token: str
    session_name: str
    log_level: str
    port: int


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
        )

    return _CONFIG
