"""
bot/handlers/callbacks.py

Central Telegram callback router.

Responsibilities
----------------
- Route callback queries to the correct feature handler
- Prevent callback collisions
- Validate callback ownership where required
- Provide a consistent fallback for unknown callbacks
- Handle expired/stale buttons
- Keep callback parsing in one place

Callback namespaces
-------------------
search:
file:
files:
premium:
settings:
group:
verification:
admin:
user:
broadcast:
pagination:
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


# ============================================================================
# Types
# ============================================================================

CallbackHandler = Callable[
    [Client, CallbackQuery],
    Awaitable[Any],
]


@dataclass(frozen=True)
class CallbackRoute:
    """
    Registered callback route.
    """

    namespace: str

    handler: CallbackHandler

    description: str = ""


# ============================================================================
# Constants
# ============================================================================

MAX_CALLBACK_LENGTH = 64

UNKNOWN_CALLBACK_TEXT = (
    "⚠️ This button is no longer available."
)

GENERIC_CALLBACK_ERROR = (
    "❌ Something went wrong. Please try again."
)

CALLBACK_SUCCESS_TEXT = (
    "Done."
)


# ============================================================================
# Router
# ============================================================================

class CallbackRouter:
    """
    Lightweight namespace-based callback router.

    Examples:

        search:query:abc
        premium:plans
        settings:menu
        group:stats:-100123
        verification:approve:123

    The first component determines the handler.
    """

    def __init__(self) -> None:

        self._routes: dict[
            str,
            CallbackRoute,
        ] = {}

    def register(
        self,
        namespace: str,
        handler: CallbackHandler,
        *,
        description: str = "",
    ) -> None:

        namespace = normalize_namespace(
            namespace
        )

        if not namespace:
            raise ValueError(
                "Callback namespace cannot be empty."
            )

        if namespace in self._routes:

            logger.warning(
                "Replacing callback route: %s",
                namespace,
            )

        self._routes[namespace] = CallbackRoute(
            namespace=namespace,
            handler=handler,
            description=description,
        )

    def unregister(
        self,
        namespace: str,
    ) -> None:

        self._routes.pop(
            normalize_namespace(
                namespace
            ),
            None,
        )

    def get(
        self,
        namespace: str,
    ) -> Optional[CallbackRoute]:

        return self._routes.get(
            normalize_namespace(
                namespace
            )
        )

    def resolve(
        self,
        data: str,
    ) -> Optional[CallbackRoute]:

        namespace = extract_namespace(
            data
        )

        if not namespace:
            return None

        return self.get(
            namespace
        )

    def namespaces(
        self,
    ) -> list[str]:

        return sorted(
            self._routes.keys()
        )

    async def dispatch(
        self,
        client: Client,
        callback_query: CallbackQuery,
    ) -> bool:

        data = (
            callback_query.data
            or ""
        )

        route = self.resolve(
            data
        )

        if route is None:
            return False

        try:

            result = await route.handler(
                client,
                callback_query,
            )

            return (
                True
                if result is None
                else bool(result)
            )

        except Exception:

            logger.exception(
                "Callback route failed: %s",
                data,
            )

            await safe_callback_error(
                callback_query
            )

            return True


# ============================================================================
# Global router
# ============================================================================

router = CallbackRouter()


# ============================================================================
# Parsing
# ============================================================================

def normalize_namespace(
    namespace: str,
) -> str:

    return str(
        namespace or ""
    ).strip().lower()


def extract_namespace(
    data: Optional[str],
) -> Optional[str]:

    if not data:
        return None

    data = str(
        data
    ).strip()

    if not data:
        return None

    namespace = data.split(
        ":",
        1,
    )[0]

    return normalize_namespace(
        namespace
    )


def split_callback(
    data: Optional[str],
) -> list[str]:

    if not data:
        return []

    return str(
        data
    ).split(":")


def callback_namespace(
    data: Optional[str],
) -> Optional[str]:

    parts = split_callback(
        data
    )

    if not parts:
        return None

    return normalize_namespace(
        parts[0]
    )


def callback_action(
    data: Optional[str],
) -> Optional[str]:

    parts = split_callback(
        data
    )

    if len(parts) < 2:
        return None

    return parts[1]


def callback_args(
    data: Optional[str],
) -> list[str]:

    parts = split_callback(
        data
    )

    if len(parts) <= 2:
        return []

    return parts[2:]


def callback_arg(
    data: Optional[str],
    index: int,
    default: Optional[str] = None,
) -> Optional[str]:

    args = callback_args(
        data
    )

    if index < 0:
        return default

    if index >= len(args):
        return default

    return args[index]


def safe_int(
    value: Any,
    default: Optional[int] = None,
) -> Optional[int]:

    try:
        return int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return default


# ============================================================================
# Callback validation
# ============================================================================

def validate_callback_data(
    data: Optional[str],
) -> bool:

    if not data:
        return False

    if len(
        data
    ) > MAX_CALLBACK_LENGTH:
        return False

    if "\n" in data:
        return False

    if "\r" in data:
        return False

    return True


def is_namespace(
    data: Optional[str],
    namespace: str,
) -> bool:

    return (
        callback_namespace(
            data
        )
        == normalize_namespace(
            namespace
        )
    )


def is_action(
    data: Optional[str],
    namespace: str,
    action: str,
) -> bool:

    return (
        callback_namespace(
            data
        )
        == normalize_namespace(
            namespace
        )
        and callback_action(
            data
        )
        == str(
            action
        ).strip().lower()
    )


# ============================================================================
# Telegram helpers
# ============================================================================

async def safe_answer(
    callback_query: CallbackQuery,
    text: Optional[str] = None,
    *,
    show_alert: bool = False,
) -> None:

    try:

        await callback_query.answer(
            text=text,
            show_alert=show_alert,
        )

    except RPCError:
        pass

    except Exception:

        logger.debug(
            "Unable to answer callback.",
            exc_info=True,
        )


async def safe_callback_error(
    callback_query: CallbackQuery,
) -> None:

    await safe_answer(
        callback_query,
        GENERIC_CALLBACK_ERROR,
        show_alert=True,
    )


async def safe_edit_text(
    callback_query: CallbackQuery,
    text: str,
    *,
    reply_markup: Optional[
        InlineKeyboardMarkup
    ] = None,
) -> bool:

    message = (
        callback_query.message
    )

    if message is None:
        return False

    try:

        await message.edit_text(
            text,
            reply_markup=reply_markup,
        )

        return True

    except RPCError:

        return False

    except Exception:

        logger.exception(
            "Unable to edit callback message."
        )

        return False


async def safe_edit_markup(
    callback_query: CallbackQuery,
    reply_markup: Optional[
        InlineKeyboardMarkup
    ] = None,
) -> bool:

    message = (
        callback_query.message
    )

    if message is None:
        return False

    try:

        await message.edit_reply_markup(
            reply_markup=reply_markup
        )

        return True

    except RPCError:

        return False

    except Exception:

        logger.exception(
            "Unable to edit callback markup."
        )

        return False


async def safe_delete_message(
    callback_query: CallbackQuery,
) -> bool:

    message = (
        callback_query.message
    )

    if message is None:
        return False

    try:

        await message.delete()

        return True

    except RPCError:

        return False

    except Exception:

        logger.exception(
            "Unable to delete callback message."
        )

        return False


# ============================================================================
# Ownership helpers
# ============================================================================

def callback_user_id(
    callback_query: CallbackQuery,
) -> Optional[int]:

    user = (
        callback_query.from_user
    )

    if user is None:
        return None

    return int(
        user.id
    )


def callback_message_chat_id(
    callback_query: CallbackQuery,
) -> Optional[int]:

    message = (
        callback_query.message
    )

    if message is None:
        return None

    chat = message.chat

    if chat is None:
        return None

    return int(
        chat.id
    )


def callback_message_user_id(
    callback_query: CallbackQuery,
) -> Optional[int]:

    message = (
        callback_query.message
    )

    if message is None:
        return None

    from_user = (
        message.from_user
    )

    if from_user is None:
        return None

    return int(
        from_user.id
    )


def callback_belongs_to_user(
    callback_query: CallbackQuery,
    expected_user_id: int,
) -> bool:

    actual = callback_user_id(
        callback_query
    )

    if actual is None:
        return False

    return (
        actual
        == int(
            expected_user_id
        )
    )


def callback_belongs_to_chat(
    callback_query: CallbackQuery,
    expected_chat_id: int,
) -> bool:

    actual = callback_message_chat_id(
        callback_query
    )

    if actual is None:
        return False

    return (
        actual
        == int(
            expected_chat_id
        )
    )


# ============================================================================
# Ownership enforcement
# ============================================================================

async def require_callback_user(
    callback_query: CallbackQuery,
    expected_user_id: int,
) -> bool:

    if callback_belongs_to_user(
        callback_query,
        expected_user_id,
    ):
        return True

    await safe_answer(
        callback_query,
        "🚫 This button belongs to another user.",
        show_alert=True,
    )

    return False


async def require_callback_chat(
    callback_query: CallbackQuery,
    expected_chat_id: int,
) -> bool:

    if callback_belongs_to_chat(
        callback_query,
        expected_chat_id,
    ):
        return True

    await safe_answer(
        callback_query,
        "🚫 This button belongs to another chat.",
        show_alert=True,
    )

    return False


# ============================================================================
# Default routes
# ============================================================================

async def handle_unknown_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:

    await safe_answer(
        callback_query,
        UNKNOWN_CALLBACK_TEXT,
        show_alert=True,
    )

    return True


async def handle_close_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:

    await safe_answer(
        callback_query
    )

    await safe_delete_message(
        callback_query
    )

    return True


# ============================================================================
# Dynamic handler imports
# ============================================================================

def import_handler(
    module_name: str,
    function_name: str,
) -> Optional[CallbackHandler]:
    """
    Import a callback handler lazily.

    Lazy imports prevent circular imports between handlers.
    """

    try:

        module = __import__(
            module_name,
            fromlist=[
                function_name
            ],
        )

        handler = getattr(
            module,
            function_name,
            None,
        )

        if handler is None:
            return None

        return handler

    except ImportError:

        logger.debug(
            "Optional callback handler unavailable: %s.%s",
            module_name,
            function_name,
        )

        return None

    except Exception:

        logger.exception(
            "Unable to import callback handler: %s.%s",
            module_name,
            function_name,
        )

        return None


# ============================================================================
# Route registration
# ============================================================================

def register_default_routes() -> None:
    """
    Register feature namespaces.

    Missing modules are ignored so the project can be developed
    incrementally.
    """

    route_definitions = [
        (
            "search",
            "bot.handlers.search",
            "search_callback",
            "Search callbacks",
        ),
        (
            "file",
            "bot.handlers.files",
            "file_callback",
            "File callbacks",
        ),
        (
            "files",
            "bot.handlers.files",
            "files_callback",
            "Files callbacks",
        ),
        (
            "premium",
            "bot.handlers.premium",
            "premium_callback",
            "Premium callbacks",
        ),
        (
            "settings",
            "bot.handlers.settings",
            "settings_callback",
            "Settings callbacks",
        ),
        (
            "group",
            "bot.handlers.groups",
            "group_callback",
            "Group callbacks",
        ),
        (
            "verification",
            "bot.handlers.verification",
            "verification_callback",
            "Verification callbacks",
        ),
        (
            "admin",
            "bot.handlers.admin",
            "admin_callback",
            "Admin callbacks",
        ),
        (
            "user",
            "bot.handlers.user",
            "user_callback",
            "User callbacks",
        ),
        (
            "broadcast",
            "bot.handlers.broadcast",
            "broadcast_callback",
            "Broadcast callbacks",
        ),
    ]

    for (
        namespace,
        module_name,
        function_name,
        description,
    ) in route_definitions:

        handler = import_handler(
            module_name,
            function_name,
        )

        if handler is None:
            continue

        router.register(
            namespace,
            handler,
            description=description,
        )

    router.register(
        "close",
        handle_close_callback,
        description="Generic close callback",
    )


# ============================================================================
# Specialized callback dispatch
# ============================================================================

async def dispatch_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:
    """
    Dispatch one callback query.

    This is the only function the global Pyrogram callback handler needs.
    """

    data = (
        callback_query.data
        or ""
    )

    if not validate_callback_data(
        data
    ):

        await safe_answer(
            callback_query,
            UNKNOWN_CALLBACK_TEXT,
            show_alert=True,
        )

        return True

    namespace = extract_namespace(
        data
    )

    if namespace is None:

        await handle_unknown_callback(
            client,
            callback_query,
        )

        return True

    route = router.resolve(
        data
    )

    if route is None:

        await handle_unknown_callback(
            client,
            callback_query,
        )

        return True

    try:

        result = await route.handler(
            client,
            callback_query,
        )

        if result is None:
            return True

        return bool(
            result
        )

    except Exception:

        logger.exception(
            "Unhandled callback exception: %s",
            data,
        )

        await safe_callback_error(
            callback_query
        )

        return True


# ============================================================================
# Generic callback helper
# ============================================================================

async def answer_success(
    callback_query: CallbackQuery,
    text: str = CALLBACK_SUCCESS_TEXT,
) -> None:

    await safe_answer(
        callback_query,
        text,
    )


async def answer_error(
    callback_query: CallbackQuery,
    text: str,
) -> None:

    await safe_answer(
        callback_query,
        text,
        show_alert=True,
    )


# ============================================================================
# Callback factories
# ============================================================================

def make_callback(
    namespace: str,
    action: str,
    *args: Any,
) -> str:
    """
    Build callback data safely.

    Telegram callback_data has a strict size limit, so callers should
    keep IDs compact.
    """

    parts = [
        normalize_namespace(
            namespace
        ),
        str(
            action
        ).strip(),
    ]

    for value in args:

        if value is None:
            continue

        parts.append(
            str(value)
        )

    result = ":".join(
        parts
    )

    if len(result) > MAX_CALLBACK_LENGTH:

        raise ValueError(
            "Callback data exceeds Telegram's callback_data limit."
        )

    return result


# ============================================================================
# Common UI callbacks
# ============================================================================

async def handle_back_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:
    """
    Generic back callback.

    Feature handlers can override this by registering a more specific
    namespace.
    """

    await safe_answer(
        callback_query
    )

    return True


router.register(
    "close",
    handle_close_callback,
    description="Close UI",
)

router.register(
    "back",
    handle_back_callback,
    description="Back UI",
)


# ============================================================================
# Global callback handler
# ============================================================================

async def global_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Main callback entry point.
    """

    try:

        await dispatch_callback(
            client,
            callback_query,
        )

    except Exception:

        logger.exception(
            "Global callback handler failed"
        )

        await safe_callback_error(
            callback_query
        )


# ============================================================================
# Health/debug helpers
# ============================================================================

def route_exists(
    namespace: str,
) -> bool:

    return (
        router.get(
            namespace
        )
        is not None
    )


def get_registered_routes() -> list[str]:

    return router.namespaces()


def describe_routes() -> list[dict[str, str]]:

    result = []

    for namespace in router.namespaces():

        route = router.get(
            namespace
        )

        if route is None:
            continue

        result.append(
            {
                "namespace": route.namespace,
                "description": route.description,
                "handler": getattr(
                    route.handler,
                    "__name__",
                    str(
                        route.handler
                    ),
                ),
            }
        )

    return result


# ============================================================================
# Explicit Pyrogram registration
# ============================================================================

def register(
    app: Client,
) -> None:
    """
    Register the global callback dispatcher.

    IMPORTANT:
    Use this OR the @Client.on_callback_query plugin handler below.
    Do not enable both.
    """

    from pyrogram.handlers import (
        CallbackQueryHandler,
    )

    register_default_routes()

    app.add_handler(
        CallbackQueryHandler(
            global_callback_handler,
            filters.regex(
                r".+"
            ),
        )
    )

    logger.info(
        "Registered central callback router."
    )


# ============================================================================
# Plugin-compatible registration
# ============================================================================

@Client.on_callback_query(
    filters.regex(
        r".+"
    )
)
async def callback_router_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Pyrogram plugin-compatible callback handler.

    If plugin discovery is used, this function can be used directly.
    """

    await global_callback_handler(
        client,
        callback_query,
    )


# ============================================================================
# Initialization
# ============================================================================

def initialize() -> CallbackRouter:
    """
    Initialize and return the callback router.
    """

    register_default_routes()

    return router


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CallbackRoute",
    "CallbackRouter",
    "router",
    "initialize",
    "register",
    "dispatch_callback",
    "global_callback_handler",
    "callback_namespace",
    "callback_action",
    "callback_args",
    "callback_arg",
    "make_callback",
    "validate_callback_data",
    "is_namespace",
    "is_action",
    "callback_user_id",
    "callback_message_chat_id",
    "callback_belongs_to_user",
    "callback_belongs_to_chat",
    "require_callback_user",
    "require_callback_chat",
    "safe_answer",
    "safe_edit_text",
    "safe_edit_markup",
    "safe_delete_message",
    "answer_success",
    "answer_error",
    "route_exists",
    "get_registered_routes",
    "describe_routes",
]