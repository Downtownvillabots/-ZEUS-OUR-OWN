"""
bot.integration

Integration and composition layer.

This package connects the application's existing:
    - core
    - database
    - services
    - middleware
    - handlers
    - keyboards
    - app

The integration layer should contain wiring and validation,
not business logic.
"""

from .wiring import (
    ApplicationWiring,
    build_wiring,
)
from .service_registry import (
    ServiceRegistry,
)
from .handler_registry import (
    HandlerRegistry,
)
from .middleware_registry import (
    MiddlewareRegistry,
)
from .health import (
    HealthChecker,
)
from .checks import (
    StartupChecker,
)

__all__ = [
    "ApplicationWiring",
    "build_wiring",
    "ServiceRegistry",
    "HandlerRegistry",
    "MiddlewareRegistry",
    "HealthChecker",
    "StartupChecker",
]