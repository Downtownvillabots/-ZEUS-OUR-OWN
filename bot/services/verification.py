"""
bot/services/verification.py

Verification workflow for the new bot.

Responsibilities:
    - First verification
    - Second verification
    - Third verification
    - Verification token validation
    - Verification URL generation
    - Verification state management
    - Access checks
    - Daily verification compatibility
    - Integration with the shortener service

The shortener service handles URL shortening.
This module handles the actual verification workflow.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

from bot.services.shortener import (
    FIRST,
    SECOND,
    THIRD,
    ShortenerManager,
    shortener,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

VALID_LAYERS = {
    FIRST,
    SECOND,
    THIRD,
}


# ============================================================================
# Data classes
# ============================================================================

@dataclass
class VerificationState:
    """
    Current verification state for a user.
    """

    user_id: int

    first_verified: bool = False
    second_verified: bool = False
    third_verified: bool = False

    required_layer: Optional[int] = None

    @property
    def fully_verified(self) -> bool:
        return self.required_layer is None


@dataclass
class VerificationResult:
    """
    Result returned after a verification operation.
    """

    success: bool
    user_id: int

    layer: Optional[int] = None

    token: Optional[str] = None

    verification_url: Optional[str] = None

    shortened_url: Optional[str] = None

    error: Optional[str] = None

    state: Optional[VerificationState] = None


# ============================================================================
# Utility
# ============================================================================

def utcnow() -> datetime:
    """
    Current timezone-aware UTC datetime.
    """
    return datetime.now(
        timezone.utc
    )


# ============================================================================
# Verification service
# ============================================================================

class VerificationService:
    """
    Main verification workflow.

    The service sits between handlers and ShortenerManager.

    Handler
       |
       v
    VerificationService
       |
       +---- ShortenerManager
       |
       +---- Database
    """

    def __init__(
        self,
        db=None,
        shortener_service: Optional[
            ShortenerManager
        ] = None,
    ):
        self.db = db

        self.shortener = (
            shortener_service
            or shortener
        )

        if db is not None:
            self.shortener.set_database(
                db
            )

    # ========================================================================
    # Database
    # ========================================================================

    def set_database(
        self,
        db,
    ):
        """
        Bind database after service creation.
        """
        self.db = db

        self.shortener.set_database(
            db
        )

    def _require_database(self):
        if self.db is None:
            raise RuntimeError(
                "VerificationService database is not configured"
            )

        return self.db

    # ========================================================================
    # User state
    # ========================================================================

    async def get_user_state(
        self,
        user_id: int,
    ) -> dict:
        """
        Get raw verification state from database.
        """
        db = self._require_database()

        return await db.get_notcopy_user(
            int(user_id)
        )

    async def get_state(
        self,
        user_id: int,
        group_id: int,
    ) -> VerificationState:
        """
        Build normalized verification state.
        """

        user_id = int(user_id)
        group_id = int(group_id)

        first_verified = (
            await self.shortener.is_first_verified(
                user_id
            )
        )

        second_verified = (
            await self.shortener.is_second_verified(
                user_id
            )
        )

        third_verified = (
            await self.shortener.is_third_verified(
                user_id
            )
        )

        required_layer = (
            await self.shortener.get_required_layer(
                user_id,
                group_id,
            )
        )

        return VerificationState(
            user_id=user_id,
            first_verified=first_verified,
            second_verified=second_verified,
            third_verified=third_verified,
            required_layer=required_layer,
        )

    # ========================================================================
    # Layer validation
    # ========================================================================

    @staticmethod
    def validate_layer(
        layer: int,
    ) -> int:
        """
        Validate verification layer.
        """

        try:
            layer = int(layer)
        except (
            TypeError,
            ValueError,
        ):
            raise ValueError(
                "Verification layer must be an integer"
            )

        if layer not in VALID_LAYERS:
            raise ValueError(
                f"Invalid verification layer: {layer}"
            )

        return layer

    # ========================================================================
    # Individual verification checks
    # ========================================================================

    async def is_verified(
        self,
        user_id: int,
        layer: int,
    ) -> bool:
        """
        Check one verification layer.
        """

        layer = self.validate_layer(
            layer
        )

        user_id = int(
            user_id
        )

        if layer == FIRST:
            return await self.shortener.is_first_verified(
                user_id
            )

        if layer == SECOND:
            return await self.shortener.is_second_verified(
                user_id
            )

        if layer == THIRD:
            return await self.shortener.is_third_verified(
                user_id
            )

        return False

    async def verify(
        self,
        user_id: int,
        layer: int,
    ) -> bool:
        """
        Mark a layer as verified.
        """

        layer = self.validate_layer(
            layer
        )

        return await self.shortener.verify_user(
            int(user_id),
            layer,
        )

    # ========================================================================
    # Verification timestamp helpers
    # ========================================================================

    async def verify_first(
        self,
        user_id: int,
    ) -> bool:
        """
        Complete first verification.
        """
        return await self.shortener.set_first_verified(
            int(user_id)
        )

    async def verify_second(
        self,
        user_id: int,
    ) -> bool:
        """
        Complete second verification.
        """
        return await self.shortener.set_second_verified(
            int(user_id)
        )

    async def verify_third(
        self,
        user_id: int,
    ) -> bool:
        """
        Complete third verification.
        """
        return await self.shortener.set_third_verified(
            int(user_id)
        )

    # ========================================================================
    # Token handling
    # ========================================================================

    async def get_token(
        self,
        user_id: int,
        token: str,
    ) -> Optional[dict]:
        """
        Retrieve verification token record.
        """

        token = str(
            token or ""
        ).strip()

        if not token:
            return None

        return await self.shortener.get_verification(
            int(user_id),
            token,
        )

    async def validate_token(
        self,
        user_id: int,
        token: str,
    ) -> tuple[
        bool,
        Optional[dict],
    ]:
        """
        Validate a verification token.
        """

        token = str(
            token or ""
        ).strip()

        if not token:
            return False, None

        return await self.shortener.validate_verification(
            int(user_id),
            token,
        )

    async def consume_token(
        self,
        user_id: int,
        token: str,
    ) -> VerificationResult:
        """
        Validate and consume a verification token.

        A token can only be used if it exists and has not expired.
        """

        user_id = int(
            user_id
        )

        token = str(
            token or ""
        ).strip()

        if not token:
            return VerificationResult(
                success=False,
                user_id=user_id,
                error="missing_token",
            )

        valid, record = (
            await self.validate_token(
                user_id,
                token,
            )
        )

        if not valid:
            return VerificationResult(
                success=False,
                user_id=user_id,
                token=token,
                error="invalid_or_expired_token",
            )

        if not record:
            return VerificationResult(
                success=False,
                user_id=user_id,
                token=token,
                error="verification_not_found",
            )

        layer = record.get(
            "layer"
        )

        try:
            layer = self.validate_layer(
                layer
            )
        except ValueError:
            return VerificationResult(
                success=False,
                user_id=user_id,
                token=token,
                error="invalid_layer",
            )

        verified = await self.verify(
            user_id,
            layer,
        )

        if not verified:
            return VerificationResult(
                success=False,
                user_id=user_id,
                token=token,
                layer=layer,
                error="unable_to_update_verification",
            )

        await self._mark_token_consumed(
            user_id,
            token,
        )

        return VerificationResult(
            success=True,
            user_id=user_id,
            token=token,
            layer=layer,
        )

    async def _mark_token_consumed(
        self,
        user_id: int,
        token: str,
    ):
        """
        Mark a verification token as used.

        We intentionally retain the token record instead of deleting it.
        This provides useful audit/debug information.
        """

        db = self._require_database()

        await db.update_verify_id_info(
            int(user_id),
            str(token),
            {
                "verified": True,
                "verified_at": utcnow(),
            },
        )

    # ========================================================================
    # Verification URL generation
    # ========================================================================

    async def create_verification_link(
        self,
        user_id: int,
        group_id: int,
        original_url: str,
        layer: int,
        callback_base_url: str,
    ) -> VerificationResult:
        """
        Create a complete verification URL.

        Flow:

            Original URL
                  |
                  v
            Verification URL
                  |
                  v
              Shortener
                  |
                  v
            User completes verification
        """

        user_id = int(
            user_id
        )

        group_id = int(
            group_id
        )

        layer = self.validate_layer(
            layer
        )

        try:
            result = (
                await self.shortener.build_verification(
                    original_url=original_url,
                    user_id=user_id,
                    group_id=group_id,
                    layer=layer,
                    callback_base_url=callback_base_url,
                )
            )

        except Exception as exc:
            logger.exception(
                "Unable to create verification link"
            )

            return VerificationResult(
                success=False,
                user_id=user_id,
                layer=layer,
                error=str(exc),
            )

        if not result:
            return VerificationResult(
                success=False,
                user_id=user_id,
                layer=layer,
                error="unable_to_create_verification",
            )

        return VerificationResult(
            success=True,
            user_id=user_id,
            layer=layer,
            token=result.get(
                "token"
            ),
            verification_url=result.get(
                "verification_url"
            ),
            shortened_url=result.get(
                "shortened_url"
            ),
        )

    # ========================================================================
    # Automatic verification flow
    # ========================================================================

    async def create_next_verification(
        self,
        user_id: int,
        group_id: int,
        original_url: str,
        callback_base_url: str,
    ) -> VerificationResult:
        """
        Automatically determine the next required verification layer
        and create its verification link.
        """

        user_id = int(
            user_id
        )

        group_id = int(
            group_id
        )

        required_layer = (
            await self.shortener.get_required_layer(
                user_id,
                group_id,
            )
        )

        if required_layer is None:
            return VerificationResult(
                success=True,
                user_id=user_id,
                error=None,
                state=await self.get_state(
                    user_id,
                    group_id,
                ),
            )

        return await self.create_verification_link(
            user_id=user_id,
            group_id=group_id,
            original_url=original_url,
            layer=required_layer,
            callback_base_url=callback_base_url,
        )

    # ========================================================================
    # Access control
    # ========================================================================

    async def check_access(
        self,
        user_id: int,
        group_id: int,
    ) -> VerificationState:
        """
        Check whether a user can access protected content.
        """

        return await self.get_state(
            int(user_id),
            int(group_id),
        )

    async def is_access_allowed(
        self,
        user_id: int,
        group_id: int,
    ) -> bool:
        """
        Return True if the user currently satisfies verification rules.
        """

        state = await self.get_state(
            int(user_id),
            int(group_id),
        )

        return state.fully_verified

    async def require_verification(
        self,
        user_id: int,
        group_id: int,
    ) -> Optional[int]:
        """
        Return required verification layer.

        None means access is allowed.
        """

        state = await self.get_state(
            int(user_id),
            int(group_id),
        )

        return state.required_layer

    # ========================================================================
    # First verification
    # ========================================================================

    async def needs_first_verification(
        self,
        user_id: int,
        group_id: int,
    ) -> bool:
        """
        Check whether first verification is needed.
        """

        layers = (
            await self.shortener.get_available_layers(
                int(group_id)
            )
        )

        if FIRST not in layers:
            return False

        return not await self.is_verified(
            user_id,
            FIRST,
        )

    # ========================================================================
    # Second verification
    # ========================================================================

    async def needs_second_verification(
        self,
        user_id: int,
        group_id: int,
    ) -> bool:
        """
        Check whether second verification is required.
        """

        return await self.shortener.requires_second_verification(
            int(user_id),
            int(group_id),
        )

    # ========================================================================
    # Third verification
    # ========================================================================

    async def needs_third_verification(
        self,
        user_id: int,
        group_id: int,
    ) -> bool:
        """
        Check whether third verification is required.
        """

        return await self.shortener.requires_third_verification(
            int(user_id),
            int(group_id),
        )

    # ========================================================================
    # Reset verification
    # ========================================================================

    async def reset_user(
        self,
        user_id: int,
    ) -> bool:
        """
        Reset all verification timestamps for a user.

        Useful for admin commands/testing.
        """

        db = self._require_database()

        result = await db.update_notcopy_user(
            int(user_id),
            {
                "last_verified": datetime(
                    2019,
                    1,
                    1,
                    tzinfo=timezone.utc,
                ),
                "second_time_verified": datetime(
                    2019,
                    1,
                    1,
                    tzinfo=timezone.utc,
                ),
                "third_time_verified": datetime(
                    2019,
                    1,
                    1,
                    tzinfo=timezone.utc,
                ),
            },
        )

        return bool(
            result
        )

    # ========================================================================
    # Token cleanup
    # ========================================================================

    async def delete_token(
        self,
        user_id: int,
        token: str,
    ) -> bool:
        """
        Delete a verification token.

        Kept separate because cleanup can later become a scheduled job.
        """

        db = self._require_database()

        collection = getattr(
            db,
            "verify_id",
            None,
        )

        if collection is None:
            return False

        result = await collection.delete_one(
            {
                "user_id": int(user_id),
                "hash": str(token),
            }
        )

        return (
            result.deleted_count > 0
        )

    async def cleanup_user_tokens(
        self,
        user_id: int,
    ) -> int:
        """
        Delete all verification tokens belonging to a user.
        """

        db = self._require_database()

        collection = getattr(
            db,
            "verify_id",
            None,
        )

        if collection is None:
            return 0

        result = await collection.delete_many(
            {
                "user_id": int(user_id),
            }
        )

        return int(
            result.deleted_count
        )

    # ========================================================================
    # Status representation
    # ========================================================================

    async def get_status(
        self,
        user_id: int,
        group_id: int,
    ) -> dict[str, Any]:
        """
        Return a handler-friendly verification status.
        """

        state = await self.get_state(
            int(user_id),
            int(group_id),
        )

        return {
            "user_id": state.user_id,
            "first_verified": state.first_verified,
            "second_verified": state.second_verified,
            "third_verified": state.third_verified,
            "required_layer": state.required_layer,
            "allowed": state.fully_verified,
        }


# ============================================================================
# Global service
# ============================================================================

verification = VerificationService()


# ============================================================================
# Initialization
# ============================================================================

def initialize_verification(
    db,
) -> VerificationService:
    """
    Initialize the global verification service.

    Call during application startup:

        initialize_verification(db)
    """

    verification.set_database(
        db
    )

    return verification


# ============================================================================
# Compatibility helpers
# ============================================================================

async def is_user_verified(
    user_id: int,
) -> bool:
    """
    Compatibility helper for old code.

    Checks first verification.
    """

    return await verification.is_verified(
        int(user_id),
        FIRST,
    )


async def user_verified(
    user_id: int,
) -> bool:
    """
    Compatibility helper for old second-verification checks.
    """

    return await verification.is_verified(
        int(user_id),
        SECOND,
    )


async def use_second_shortener(
    user_id: int,
    group_id: int,
) -> bool:
    """
    Compatibility helper matching the old architecture.

    Returns True when second verification should be triggered.
    """

    return await verification.needs_second_verification(
        int(user_id),
        int(group_id),
    )


async def use_third_shortener(
    user_id: int,
    group_id: int,
) -> bool:
    """
    Compatibility helper matching the old architecture.
    """

    return await verification.needs_third_verification(
        int(user_id),
        int(group_id),
    )


async def verify_token(
    user_id: int,
    token: str,
) -> VerificationResult:
    """
    Validate and consume verification token.
    """

    return await verification.consume_token(
        int(user_id),
        token,
    )


async def verification_required(
    user_id: int,
    group_id: int,
) -> Optional[int]:
    """
    Return required verification layer.
    """

    return await verification.require_verification(
        int(user_id),
        int(group_id),
    )


__all__ = [
    "FIRST",
    "SECOND",
    "THIRD",
    "VerificationState",
    "VerificationResult",
    "VerificationService",
    "verification",
    "initialize_verification",
    "is_user_verified",
    "user_verified",
    "use_second_shortener",
    "use_third_shortener",
    "verify_token",
    "verification_required",
]