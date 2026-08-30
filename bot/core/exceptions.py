"""
bot.core.exceptions

Application exception hierarchy.

Handlers should catch specific application exceptions where
appropriate instead of catching Exception everywhere.
"""

from __future__ import annotations

from typing import Any, Optional


class BotError(Exception):
    """Base exception for expected application errors."""

    code = "BOT_ERROR"

    def __init__(
        self,
        message: str = "An application error occurred.",
        *,
        code: Optional[str] = None,
        user_message: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:

        super().__init__(message)

        self.message = message

        self.code = (
            code
            or self.code
        )

        self.user_message = (
            user_message
            or message
        )

        self.details = (
            details
            or {}
        )

    def __str__(self) -> str:
        return self.message


class ConfigurationError(BotError):

    code = "CONFIGURATION_ERROR"

    def __init__(
        self,
        message: str = "Application configuration is invalid.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            **kwargs,
        )


class AuthenticationError(BotError):

    code = "AUTHENTICATION_ERROR"

    def __init__(
        self,
        message: str = "Authentication failed.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message="Authentication failed.",
            **kwargs,
        )


class AuthorizationError(BotError):

    code = "AUTHORIZATION_ERROR"

    def __init__(
        self,
        message: str = "You are not authorized to perform this action.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "⛔ You are not authorized "
                "to perform this action."
            ),
            **kwargs,
        )


class BannedUserError(
    AuthorizationError
):

    code = "USER_BANNED"

    def __init__(
        self,
        message: str = "User is banned.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "🚫 You are not allowed "
                "to use this bot."
            ),
            **kwargs,
        )


class ValidationError(BotError):

    code = "VALIDATION_ERROR"

    def __init__(
        self,
        message: str = "Invalid input.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            **kwargs,
        )


class NotFoundError(BotError):

    code = "NOT_FOUND"

    def __init__(
        self,
        resource: str = "Resource",
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message
            or f"{resource} was not found.",
            user_message=(
                f"❌ {resource} was not found."
            ),
            **kwargs,
        )


class UserNotFoundError(
    NotFoundError
):

    code = "USER_NOT_FOUND"

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            resource="User",
            **kwargs,
        )


class FileNotFoundError(
    NotFoundError
):

    code = "FILE_NOT_FOUND"

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            resource="File",
            **kwargs,
        )


class MovieNotFoundError(
    NotFoundError
):

    code = "MOVIE_NOT_FOUND"

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            resource="Movie",
            **kwargs,
        )


class SearchError(BotError):

    code = "SEARCH_ERROR"

    def __init__(
        self,
        message: str = "Search failed.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "🔎 Search failed. "
                "Please try again."
            ),
            **kwargs,
        )


class SearchQueryError(
    SearchError
):

    code = "INVALID_SEARCH_QUERY"

    def __init__(
        self,
        message: str = "Invalid search query.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "⚠️ Please enter a valid search query."
            ),
            **kwargs,
        )


class SearchTimeoutError(
    SearchError
):

    code = "SEARCH_TIMEOUT"

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            "Search operation timed out.",
            user_message=(
                "⏳ Search is taking too long. "
                "Please try again."
            ),
            **kwargs,
        )


class DatabaseError(BotError):

    code = "DATABASE_ERROR"

    def __init__(
        self,
        message: str = "Database operation failed.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "⚠️ A database error occurred. "
                "Please try again."
            ),
            **kwargs,
        )


class DatabaseConnectionError(
    DatabaseError
):

    code = "DATABASE_CONNECTION_ERROR"


class DatabaseTimeoutError(
    DatabaseError
):

    code = "DATABASE_TIMEOUT"


class CacheError(BotError):

    code = "CACHE_ERROR"


class ExternalServiceError(
    BotError
):

    code = "EXTERNAL_SERVICE_ERROR"

    def __init__(
        self,
        service: str = "External service",
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message
            or f"{service} request failed.",
            user_message=(
                "⚠️ An external service "
                "is temporarily unavailable."
            ),
            details={
                "service": service,
                **kwargs.pop(
                    "details",
                    {},
                ),
            },
            **kwargs,
        )


class DeliveryError(
    ExternalServiceError
):

    code = "DELIVERY_ERROR"

    def __init__(
        self,
        message: str = "File delivery failed.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            service="Delivery service",
            message=message,
            user_message=(
                "📦 File delivery failed. "
                "Please try again."
            ),
            **kwargs,
        )


class ShortenerError(
    ExternalServiceError
):

    code = "SHORTENER_ERROR"


class VerificationError(BotError):

    code = "VERIFICATION_ERROR"


class VerificationRequiredError(
    VerificationError
):

    code = "VERIFICATION_REQUIRED"

    def __init__(
        self,
        message: str = "Verification is required.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "🔐 Please complete verification "
                "before continuing."
            ),
            **kwargs,
        )


class VerificationExpiredError(
    VerificationError
):

    code = "VERIFICATION_EXPIRED"

    def __init__(
        self,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            "Verification has expired.",
            user_message=(
                "⏰ Your verification has expired. "
                "Please verify again."
            ),
            **kwargs,
        )


class PremiumRequiredError(
    AuthorizationError
):

    code = "PREMIUM_REQUIRED"

    def __init__(
        self,
        message: str = "Premium subscription required.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "💎 This feature requires "
                "a Premium subscription."
            ),
            **kwargs,
        )


class PaymentError(BotError):

    code = "PAYMENT_ERROR"

    def __init__(
        self,
        message: str = "Payment operation failed.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "💳 Payment could not be completed."
            ),
            **kwargs,
        )


class PaymentAlreadyProcessedError(
    PaymentError
):

    code = "PAYMENT_ALREADY_PROCESSED"


class BroadcastError(BotError):

    code = "BROADCAST_ERROR"


class ModerationError(
    AuthorizationError
):

    code = "MODERATION_ERROR"


class RateLimitError(BotError):

    code = "RATE_LIMITED"

    def __init__(
        self,
        retry_after: float = 0.0,
        **kwargs: Any,
    ) -> None:

        super().__init__(
            "Rate limit exceeded.",
            user_message=(
                "⏳ Too many requests. "
                "Please slow down."
            ),
            details={
                "retry_after": retry_after,
                **kwargs.pop(
                    "details",
                    {},
                ),
            },
            **kwargs,
        )

        self.retry_after = float(
            retry_after
        )


class TokenError(
    AuthenticationError
):

    code = "TOKEN_ERROR"


class TokenExpiredError(
    TokenError
):

    code = "TOKEN_EXPIRED"


class TokenInvalidError(
    TokenError
):

    code = "TOKEN_INVALID"


class ConflictError(BotError):

    code = "CONFLICT"


class AlreadyExistsError(
    ConflictError
):

    code = "ALREADY_EXISTS"


class ServiceUnavailableError(
    BotError
):

    code = "SERVICE_UNAVAILABLE"

    def __init__(
        self,
        message: str = "Service temporarily unavailable.",
        **kwargs: Any,
    ) -> None:

        super().__init__(
            message,
            user_message=(
                "⚠️ The service is temporarily "
                "unavailable. Please try again later."
            ),
            **kwargs,
        )


class OperationCancelledError(
    BotError
):

    code = "OPERATION_CANCELLED"


class ExternalAPIError(
    ExternalServiceError
):

    code = "EXTERNAL_API_ERROR"


class IndexingError(
    ExternalServiceError
):

    code = "INDEXING_ERROR"


class ModerationActionError(
    ModerationError
):

    code = "MODERATION_ACTION_ERROR"


class BroadcastCancelledError(
    BroadcastError
):

    code = "BROADCAST_CANCELLED"


__all__ = [
    "BotError",
    "ConfigurationError",
    "AuthenticationError",
    "AuthorizationError",
    "BannedUserError",
    "ValidationError",
    "NotFoundError",
    "UserNotFoundError",
    "FileNotFoundError",
    "MovieNotFoundError",
    "SearchError",
    "SearchQueryError",
    "SearchTimeoutError",
    "DatabaseError",
    "DatabaseConnectionError",
    "DatabaseTimeoutError",
    "CacheError",
    "ExternalServiceError",
    "ExternalAPIError",
    "DeliveryError",
    "ShortenerError",
    "VerificationError",
    "VerificationRequiredError",
    "VerificationExpiredError",
    "PremiumRequiredError",
    "PaymentError",
    "PaymentAlreadyProcessedError",
    "BroadcastError",
    "BroadcastCancelledError",
    "ModerationError",
    "ModerationActionError",
    "RateLimitError",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "ConflictError",
    "AlreadyExistsError",
    "ServiceUnavailableError",
    "OperationCancelledError",
    "IndexingError",
]