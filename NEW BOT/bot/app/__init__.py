"""
bot.app

Application composition and dependency wiring.
"""

from .container import ApplicationContainer
from .application import BotApplication
from .startup import (
    create_application,
    run_application,
    run_application_async,
)

__all__ = [
    "ApplicationContainer",
    "BotApplication",
    "create_application",
    "run_application",
    "run_application_async",
]