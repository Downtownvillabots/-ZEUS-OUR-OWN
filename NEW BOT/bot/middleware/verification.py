"""
bot.middleware.verification

Verification middleware.

Responsibilities
----------------
- Determine whether a user requires verification
- Read verification status from the existing verification service
- Allow verified users through
- Allow administrators through
- Block unverified users from protected routes
- Provide a consistent verification prompt
- Store verification information in MiddlewareContext

This module does NOT implement the actual verification workflow.
The verification service/handler remains responsible for generating
verification challenges and completing verification.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.middleware import MiddlewareContext

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

VERIFICATION_CONTEXT_KEY = "verification"

VERIFICATION_REQUIRED_KEY = (
    "verification_required"
)

VERIFICATION_COMPLETED_KEY = (
    "verification_completed"
)

VERIFICATION_BLOCKED_KEY = (
    "verification_blocked"
)

DEFAULT_VERIFICATION_TEXT = (
    "🔐 <b>Verification Required</b>\n\n"
    "Please complete verification before using this feature."
)


# ============================================================================
# Result model
# ============================================================================

@dataclass
class VerificationResult:
    """
    Result of a verification check.
    """

    required: bool = False

    verified: bool = False

    user_id: Optional[int] = None

    token: Optional[str] = None

    reason: Optional[str] = None

    expires_at: Optional[Any] = None

    def to_dict(self) -> dict[str, Any]:

        return {
            "required": self.required,
            "verified": self.verified,
            "user_id": self.user_id,
            "token": self.token,
            "reason": self.reason,
            "expires_at": self.expires_at,
        }


# ============================================================================
# Lazy service access
# ============================================================================

def get_verification_service():
    """
    Load the existing verification handler/service lazily.

    This avoids circular imports during application startup.
    """

    candidates = (
        "bot.services.verification",
        "bot.handlers.verification",
    )

    for module_name in candidates:

        try:

            module = __import__(
                module_name,
                fromlist=["*"],
            )

            return module

        except ImportError:

            continue

        except Exception:

            logger.exception(
                "Unable to import verification module: %s",
                module_name,
            )

            continue

    return None


# ============================================================================
# Generic service invocation
# ============================================================================

async def call_service(
    service: Any,
    names: tuple[str, ...],
    *args,
    **kwargs,
):
    """
    Call the first available service function.

    Returns:
        (found, result)
    """

    if service is None:
        return False, None

    for name in names:

        function = getattr(
            service,
            name,
            None,
        )

        if function is None:
            continue

        try:

            result = function(
                *args,
                **kwargs,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return True, result

        except TypeError:

            # Signature mismatch. Try the next compatible method.
            logger.debug(
                "Verification method signature mismatch: %s",
                name,
                exc_info=True,
            )

            continue

        except Exception:

            logger.exception(
                "Verification service method failed: %s",
                name,
            )

            return True, None

    return False, None


# ============================================================================
# Update helpers
# ============================================================================

def get_user_id(
    update: Any,
) -> Optional[int]:

    user = getattr(
        update,
        "from_user",
        None,
    )

    if user is None:

        user = getattr(
            update,
            "user",
            None,
        )

    if user is None:
        return None

    try:

        return int(
            user.id
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):

        return None


# ============================================================================
# Configuration
# ============================================================================

def get_config(
    client: Client,
) -> Any:

    return getattr(
        client,
        "config",
        None,
    )


def config_value(
    client: Client,
    *keys: str,
    default: Any = None,
) -> Any:

    config = get_config(
        client
    )

    if config is None:
        return default

    if isinstance(
        config,
        dict,
    ):

        for key in keys:

            if key in config:

                return config[
                    key
                ]

        return default

    for key in keys:

        try:

            value = getattr(
                config,
                key,
            )

            if value is not None:

                return value

        except AttributeError:

            continue

    return default


def verification_enabled(
    client: Client,
) -> bool:
    """
    Determine whether verification is globally enabled.

    Defaults to True when no explicit configuration is supplied because
    this middleware is intended for protected deployments.
    """

    value = config_value(
        client,
        "verification_enabled",
        "enable_verification",
        "force_verification",
        default=True,
    )

    if isinstance(
        value,
        str,
    ):

        return value.lower() not in {
            "false",
            "0",
            "no",
            "off",
            "disabled",
        }

    return bool(
        value
    )


# ============================================================================
# Administrator bypass
# ============================================================================

async def is_admin(
    client: Client,
    user_id: Optional[int],
) -> bool:

    if user_id is None:
        return False

    try:

        from bot.middleware.auth import (
            is_admin as auth_is_admin,
        )

        return bool(
            await auth_is_admin(
                client,
                int(user_id),
            )
        )

    except Exception:

        logger.exception(
            "Unable to check administrator status."
        )

        return False


# ============================================================================
# Service response normalization
# ============================================================================

def normalize_verification_result(
    value: Any,
    *,
    user_id: Optional[int] = None,
) -> VerificationResult:

    if isinstance(
        value,
        VerificationResult,
    ):

        if (
            value.user_id is None
            and user_id is not None
        ):

            value.user_id = user_id

        return value

    if value is None:

        return VerificationResult(
            required=False,
            verified=False,
            user_id=user_id,
        )

    if isinstance(
        value,
        bool,
    ):

        return VerificationResult(
            required=True,
            verified=value,
            user_id=user_id,
        )

    if isinstance(
        value,
        dict,
    ):

        required = value.get(
            "required",
            value.get(
                "verification_required",
                True,
            ),
        )

        verified = value.get(
            "verified",
            value.get(
                "is_verified",
                value.get(
                    "verification_completed",
                    False,
                ),
            ),
        )

        return VerificationResult(
            required=bool(
                required
            ),
            verified=bool(
                verified
            ),
            user_id=value.get(
                "user_id",
                user_id,
            ),
            token=value.get(
                "token",
                value.get(
                    "verification_token"
                ),
            ),
            reason=value.get(
                "reason"
            ),
            expires_at=value.get(
                "expires_at"
            ),
        )

    return VerificationResult(
        required=True,
        verified=bool(value),
        user_id=user_id,
    )


# ============================================================================
# Verification status
# ============================================================================

async def get_verification_status(
    client: Client,
    user_id: int,
) -> VerificationResult:
    """
    Retrieve the user's current verification status.
    """

    if not verification_enabled(
        client
    ):

        return VerificationResult(
            required=False,
            verified=True,
            user_id=user_id,
            reason="verification_disabled",
        )

    service = get_verification_service()

    found, result = await call_service(
        service,
        (
            "get_verification_status",
            "get_status",
            "verification_status",
            "check_verification",
            "get_user_verification",
        ),
        int(user_id),
    )

    if found:

        return normalize_verification_result(
            result,
            user_id=user_id,
        )

    # Try the common direct boolean functions.
    found, result = await call_service(
        service,
        (
            "is_verified",
            "is_user_verified",
            "has_verified",
            "check_verified",
        ),
        int(user_id),
    )

    if found:

        return VerificationResult(
            required=True,
            verified=bool(
                result
            ),
            user_id=user_id,
        )

    # No verification backend was found.
    #
    # We do not silently block all users here. This lets the application
    # start while the verification service is still being developed.
    logger.warning(
        "No verification status function found; allowing request."
    )

    return VerificationResult(
        required=False,
        verified=True,
        user_id=user_id,
        reason="verification_service_unavailable",
    )


# ============================================================================
# Verification requirement
# ============================================================================

async def requires_verification(
    client: Client,
    user_id: int,
) -> bool:

    status = await get_verification_status(
        client,
        user_id,
    )

    return (
        status.required
        and not status.verified
    )


async def is_verified(
    client: Client,
    user_id: int,
) -> bool:

    status = await get_verification_status(
        client,
        user_id,
    )

    return bool(
        status.verified
    )


# ============================================================================
# Verification challenge
# ============================================================================

async def create_verification(
    client: Client,
    user_id: int,
) -> Optional[Any]:
    """
    Ask the verification service to create a challenge.

    The exact implementation remains inside services/verification.py.
    """

    service = get_verification_service()

    found, result = await call_service(
        service,
        (
            "create_verification",
            "create_challenge",
            "start_verification",
            "generate_verification",
            "begin_verification",
        ),
        int(user_id),
    )

    if not found:

        return None

    return result


# ============================================================================
# Verification URL
# ============================================================================

def extract_verification_url(
    value: Any,
) -> Optional[str]:

    if value is None:
        return None

    if isinstance(
        value,
        str,
    ):

        if (
            value.startswith(
                "https://"
            )
            or value.startswith(
                "http://"
            )
        ):

            return value

        return None

    if isinstance(
        value,
        dict,
    ):

        for key in (
            "url",
            "verification_url",
            "verify_url",
            "link",
        ):

            url = value.get(
                key
            )

            if url:

                return str(
                    url
                )

    for key in (
        "url",
        "verification_url",
        "verify_url",
        "link",
    ):

        url = getattr(
            value,
            key,
            None,
        )

        if url:

            return str(
                url
            )

    return None


# ============================================================================
# UI
# ============================================================================

def build_verification_keyboard(
    verification: Optional[Any] = None,
) -> InlineKeyboardMarkup:

    url = extract_verification_url(
        verification
    )

    rows = []

    if url:

        rows.append(
            [
                InlineKeyboardButton(
                    "🔐 Verify Now",
                    url=url,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "🔄 Check Verification",
                callback_data=(
                    "verification:check"
                ),
            )
        ]
    )

    return InlineKeyboardMarkup(
        rows
    )


def build_verification_message(
    result: Optional[VerificationResult] = None,
) -> str:

    lines = [
        DEFAULT_VERIFICATION_TEXT,
    ]

    if result is not None:

        if result.reason == "expired":

            lines = [
                "⌛ <b>Verification Expired</b>\n",
                "Please start verification again.",
            ]

        elif result.reason:

            lines.extend(
                [
                    "",
                    f"ℹ️ {escape_html(result.reason)}",
                ]
            )

    lines.extend(
        [
            "",
            "Verification protects the bot from abuse.",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================================
# User-facing blocking
# ============================================================================

async def block_message(
    message: Message,
    result: VerificationResult,
    verification: Any = None,
) -> bool:

    try:

        await message.reply_text(
            build_verification_message(
                result
            ),
            reply_markup=build_verification_keyboard(
                verification
            ),
        )

        return True

    except Exception:

        logger.exception(
            "Unable to send verification prompt."
        )

        return False


async def block_callback(
    callback_query: CallbackQuery,
    result: VerificationResult,
    verification: Any = None,
) -> bool:

    try:

        await callback_query.answer(
            "🔐 Verification required.",
            show_alert=True,
        )

    except Exception:

        pass

    message = (
        callback_query.message
    )

    if message is None:
        return False

    try:

        await message.edit_text(
            build_verification_message(
                result
            ),
            reply_markup=build_verification_keyboard(
                verification
            ),
        )

        return True

    except Exception:

        logger.exception(
            "Unable to display verification prompt."
        )

        return False


# ============================================================================
# Middleware
# ============================================================================

class VerificationMiddleware:
    """
    Verification middleware.

    Administrators bypass verification.

    Verified users continue normally.

    Unverified users are shown a verification challenge.
    """

    def __init__(
        self,
        *,
        enabled: Optional[bool] = None,
        allow_admins: bool = True,
    ) -> None:

        self.enabled = enabled

        self.allow_admins = bool(
            allow_admins
        )

    async def process(
        self,
        client: Client,
        update: Any,
        context: MiddlewareContext,
        next_handler,
    ):
        """
        Process verification requirement.
        """

        if self.enabled is False:

            context.is_verified = True

            context.set(
                VERIFICATION_REQUIRED_KEY,
                False,
            )

            return await next_handler()

        if not verification_enabled(
            client
        ):

            context.is_verified = True

            context.set(
                VERIFICATION_REQUIRED_KEY,
                False,
            )

            context.set(
                VERIFICATION_COMPLETED_KEY,
                True,
            )

            return await next_handler()

        user_id = (
            context.user_id
            or get_user_id(
                update
            )
        )

        if user_id is None:

            # Authentication middleware should normally catch this.
            context.block(
                "missing_user"
            )

            return None

        if (
            self.allow_admins
            and await is_admin(
                client,
                user_id,
            )
        ):

            context.is_admin = True

            context.is_verified = True

            context.set(
                VERIFICATION_REQUIRED_KEY,
                False,
            )

            context.set(
                VERIFICATION_COMPLETED_KEY,
                True,
            )

            context.set(
                "verification_admin_bypass",
                True,
            )

            return await next_handler()

        result = await get_verification_status(
            client,
            user_id,
        )

        context.set(
            VERIFICATION_CONTEXT_KEY,
            result,
        )

        context.set(
            VERIFICATION_REQUIRED_KEY,
            result.required,
        )

        context.set(
            VERIFICATION_COMPLETED_KEY,
            result.verified,
        )

        context.is_verified = bool(
            result.verified
        )

        if (
            not result.required
            or result.verified
        ):

            return await next_handler()

        context.block(
            "verification_required"
        )

        context.set(
            VERIFICATION_BLOCKED_KEY,
            True,
        )

        challenge = await create_verification(
            client,
            user_id,
        )

        if isinstance(
            update,
            CallbackQuery,
        ):

            await block_callback(
                update,
                result,
                challenge,
            )

        elif isinstance(
            update,
            Message,
        ):

            await block_message(
                update,
                result,
                challenge,
            )

        return None


# ============================================================================
# Standalone checks
# ============================================================================

async def require_verification(
    client: Client,
    update: Any,
) -> bool:
    """
    Verify whether an update may continue.
    """

    user_id = get_user_id(
        update
    )

    if user_id is None:

        return False

    if await is_admin(
        client,
        user_id,
    ):

        return True

    result = await get_verification_status(
        client,
        user_id,
    )

    if (
        not result.required
        or result.verified
    ):

        return True

    challenge = await create_verification(
        client,
        user_id,
    )

    if isinstance(
        update,
        CallbackQuery,
    ):

        await block_callback(
            update,
            result,
            challenge,
        )

    elif isinstance(
        update,
        Message,
    ):

        await block_message(
            update,
            result,
            challenge,
        )

    return False


# ============================================================================
# Callback check
# ============================================================================

async def check_callback(
    client: Client,
    callback_query: CallbackQuery,
) -> bool:

    return await require_verification(
        client,
        callback_query,
    )


# ============================================================================
# Message check
# ============================================================================

async def check_message(
    client: Client,
    message: Message,
) -> bool:

    return await require_verification(
        client,
        message,
    )


# ============================================================================
# Context helpers
# ============================================================================

def context_verification(
    context: MiddlewareContext,
) -> Optional[VerificationResult]:

    value = context.get(
        VERIFICATION_CONTEXT_KEY
    )

    if isinstance(
        value,
        VerificationResult,
    ):

        return value

    if value is None:
        return None

    return normalize_verification_result(
        value,
        user_id=context.user_id,
    )


def context_is_verified(
    context: MiddlewareContext,
) -> bool:

    return bool(
        context.is_verified
    )


def context_requires_verification(
    context: MiddlewareContext,
) -> bool:

    result = context_verification(
        context
    )

    if result is None:

        return bool(
            context.get(
                VERIFICATION_REQUIRED_KEY,
                False,
            )
        )

    return (
        result.required
        and not result.verified
    )


def context_verification_blocked(
    context: MiddlewareContext,
) -> bool:

    return bool(
        context.get(
            VERIFICATION_BLOCKED_KEY,
            False,
        )
    )


# ============================================================================
# Decorator
# ============================================================================

def verification_required(
    function,
):
    """
    Protect a standalone handler with verification.
    """

    async def wrapper(
        client: Client,
        update: Any,
        *args,
        **kwargs,
    ):

        allowed = await require_verification(
            client,
            update,
        )

        if not allowed:

            return None

        return await function(
            client,
            update,
            *args,
            **kwargs,
        )

    wrapper.__name__ = getattr(
        function,
        "__name__",
        "verification_required_handler",
    )

    wrapper.__doc__ = getattr(
        function,
        "__doc__",
        None,
    )

    return wrapper


# ============================================================================
# Verification refresh
# ============================================================================

async def refresh_status(
    client: Client,
    user_id: int,
) -> VerificationResult:

    return await get_verification_status(
        client,
        user_id,
    )


# ============================================================================
# Registration
# ============================================================================

_default_middleware: Optional[
    VerificationMiddleware
] = None


def get_default_middleware(
) -> VerificationMiddleware:

    global _default_middleware

    if _default_middleware is None:

        _default_middleware = (
            VerificationMiddleware()
        )

    return _default_middleware


def register(
    app: Client,
) -> None:

    global _default_middleware

    _default_middleware = (
        VerificationMiddleware()
    )

    logger.info(
        "Verification middleware initialized."
    )


# ============================================================================
# HTML helper
# ============================================================================

def escape_html(
    value: Any,
) -> str:

    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "VerificationResult",
    "VerificationMiddleware",
    "get_verification_status",
    "requires_verification",
    "is_verified",
    "create_verification",
    "require_verification",
    "check_callback",
    "check_message",
    "context_verification",
    "context_is_verified",
    "context_requires_verification",
    "context_verification_blocked",
    "verification_required",
    "refresh_status",
    "get_default_middleware",
    "register",
]