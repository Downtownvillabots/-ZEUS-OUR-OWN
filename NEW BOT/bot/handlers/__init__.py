"""
bot.handlers

Telegram bot handler package.

This package contains:
    - start
    - search
    - user
    - admin
    - settings
    - verification
    - files
    - broadcast
    - groups
    - premium
    - maintenance
    - callbacks
    - errors

The package intentionally avoids importing every handler at module import
time. This reduces circular-import problems and makes optional handlers
safe to develop independently.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client

logger = logging.getLogger(__name__)


# ============================================================================
# Handler definitions
# ============================================================================

@dataclass(frozen=True)
class HandlerModule:
    """
    Description of one handler module.
    """

    name: str

    module: str

    required: bool = True


HANDLER_MODULES: tuple[HandlerModule, ...] = (
    HandlerModule(
        name="start",
        module="bot.handlers.start",
    ),
    HandlerModule(
        name="search",
        module="bot.handlers.search",
    ),
    HandlerModule(
        name="user",
        module="bot.handlers.user",
    ),
    HandlerModule(
        name="admin",
        module="bot.handlers.admin",
    ),
    HandlerModule(
        name="settings",
        module="bot.handlers.settings",
    ),
    HandlerModule(
        name="verification",
        module="bot.handlers.verification",
    ),
    HandlerModule(
        name="files",
        module="bot.handlers.files",
    ),
    HandlerModule(
        name="broadcast",
        module="bot.handlers.broadcast",
    ),
    HandlerModule(
        name="groups",
        module="bot.handlers.groups",
    ),
    HandlerModule(
        name="premium",
        module="bot.handlers.premium",
    ),
    HandlerModule(
        name="maintenance",
        module="bot.handlers.maintenance",
    ),
    HandlerModule(
        name="callbacks",
        module="bot.handlers.callbacks",
    ),
    HandlerModule(
        name="errors",
        module="bot.handlers.errors",
    ),
)


# ============================================================================
# Runtime state
# ============================================================================

_initialized_apps: set[int] = set()

_loaded_modules: dict[
    str,
    Any,
] = {}


# ============================================================================
# Module loading
# ============================================================================

def load_module(
    module_path: str,
) -> Optional[Any]:
    """
    Import one handler module lazily.
    """

    if module_path in _loaded_modules:

        return _loaded_modules[
            module_path
        ]

    try:

        module = importlib.import_module(
            module_path
        )

        _loaded_modules[
            module_path
        ] = module

        return module

    except ImportError:

        logger.exception(
            "Unable to import handler module: %s",
            module_path,
        )

        return None

    except Exception:

        logger.exception(
            "Handler module initialization failed: %s",
            module_path,
        )

        return None


def get_handler_module(
    name: str,
) -> Optional[Any]:

    normalized = (
        str(name)
        .strip()
        .lower()
    )

    for definition in HANDLER_MODULES:

        if definition.name == normalized:

            return load_module(
                definition.module
            )

    return None


# ============================================================================
# Explicit registration
# ============================================================================

def register_module(
    app: Client,
    definition: HandlerModule,
) -> bool:
    """
    Register one handler module.

    Modules may expose:

        register(app)

    If the module relies exclusively on Pyrogram decorators/plugins,
    registration is considered successful after import.
    """

    module = load_module(
        definition.module
    )

    if module is None:

        if definition.required:

            logger.error(
                "Required handler unavailable: %s",
                definition.name,
            )

        else:

            logger.warning(
                "Optional handler unavailable: %s",
                definition.name,
            )

        return False

    register_function = getattr(
        module,
        "register",
        None,
    )

    if register_function is None:

        logger.debug(
            "Handler %s uses decorator/plugin registration.",
            definition.name,
        )

        return True

    try:

        register_function(
            app
        )

        logger.info(
            "Registered handler module: %s",
            definition.name,
        )

        return True

    except Exception:

        logger.exception(
            "Failed to register handler module: %s",
            definition.name,
        )

        return False


def register_all(
    app: Client,
    *,
    include_callbacks: bool = True,
    include_errors: bool = True,
) -> dict[str, bool]:
    """
    Register all handlers that expose explicit register(app).

    Returns:
        {
            "start": True,
            "search": True,
            ...
        }

    IMPORTANT:
    If the project uses Pyrogram's plugin system, do not call this
    together with plugin auto-discovery for the same modules.
    """

    app_key = id(
        app
    )

    if app_key in _initialized_apps:

        logger.warning(
            "Handlers already initialized for this app."
        )

        return {
            definition.name: True
            for definition in HANDLER_MODULES
        }

    results: dict[
        str,
        bool,
    ] = {}

    for definition in HANDLER_MODULES:

        if (
            definition.name == "callbacks"
            and not include_callbacks
        ):
            continue

        if (
            definition.name == "errors"
            and not include_errors
        ):
            continue

        results[
            definition.name
        ] = register_module(
            app,
            definition,
        )

    _initialized_apps.add(
        app_key
    )

    return results


# ============================================================================
# Selective registration
# ============================================================================

def register_selected(
    app: Client,
    names: list[str] | tuple[str, ...],
) -> dict[str, bool]:
    """
    Register only selected handler modules.

    Useful for tests and development.
    """

    results: dict[
        str,
        bool,
    ] = {}

    requested = {
        str(name)
        .strip()
        .lower()
        for name in names
    }

    for definition in HANDLER_MODULES:

        if definition.name not in requested:
            continue

        results[
            definition.name
        ] = register_module(
            app,
            definition,
        )

    return results


# ============================================================================
# Handler inspection
# ============================================================================

def list_handlers() -> list[str]:

    return [
        definition.name
        for definition in HANDLER_MODULES
    ]


def handler_definitions() -> list[dict[str, Any]]:

    return [
        {
            "name": definition.name,
            "module": definition.module,
            "required": definition.required,
        }
        for definition in HANDLER_MODULES
    ]


def is_handler_available(
    name: str,
) -> bool:

    module = get_handler_module(
        name
    )

    return module is not None


# ============================================================================
# Initialization diagnostics
# ============================================================================

def initialization_report(
    results: dict[str, bool],
) -> str:

    lines = [
        "Handler initialization report",
        "=" * 32,
    ]

    for definition in HANDLER_MODULES:

        if definition.name not in results:
            continue

        status = (
            "OK"
            if results[
                definition.name
            ]
            else "FAILED"
        )

        lines.append(
            f"{definition.name:<16} {status}"
        )

    return "\n".join(
        lines
    )


# ============================================================================
# Safe shutdown
# ============================================================================

def reset_handler_state() -> None:
    """
    Reset local initialization bookkeeping.

    Useful for tests.

    This does not remove handlers from a live Pyrogram Client.
    """

    _initialized_apps.clear()


# ============================================================================
# Public package API
# ============================================================================

__all__ = [
    "HandlerModule",
    "HANDLER_MODULES",
    "load_module",
    "get_handler_module",
    "register_module",
    "register_all",
    "register_selected",
    "list_handlers",
    "handler_definitions",
    "is_handler_available",
    "initialization_report",
    "reset_handler_state",
]