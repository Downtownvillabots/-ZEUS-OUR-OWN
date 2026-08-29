"""
DOWNTOWN VILLA
Feature loader.

Each completed feature gets its own directory under functions/.

A feature exposes:
    register(runtime)

The loader imports only registered feature packages. This prevents a
half-written future folder from accidentally becoming active.
"""

from __future__ import annotations

import importlib

from app.logging import get_logger
from app.runtime import Runtime


LOGGER = get_logger(__name__)

ENABLED_FEATURES = (
    "functions.runtime_test",
    "functions.start",
    "functions.help",
    "functions.media_indexing",
    "functions.search",
    
)


def load_functions(runtime: Runtime) -> None:
    for module_name in ENABLED_FEATURES:
        module = importlib.import_module(module_name)

        register = getattr(module, "register", None)

        if register is None:
            raise RuntimeError(
                f"Feature {module_name} does not expose register(runtime)."
            )

        register(runtime)
        LOGGER.info("Loaded feature: %s", module_name)
