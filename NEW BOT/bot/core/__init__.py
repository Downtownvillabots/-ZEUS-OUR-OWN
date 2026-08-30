"""
bot.core

Core application primitives.

This package contains configuration, constants, exceptions,
logging, and application lifecycle components.
"""

from .constants import (
    APP_NAME,
    APP_VERSION,
    ENV_DEVELOPMENT,
    ENV_PRODUCTION,
    ENV_TESTING,
)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ENV_DEVELOPMENT",
    "ENV_PRODUCTION",
    "ENV_TESTING",
]