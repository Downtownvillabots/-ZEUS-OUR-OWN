"""
bot/services/shortener.py

Centralized verification + URL shortener service.

Supports:
    - 1st shortener
    - 2nd shortener
    - 3rd shortener
    - Per-group shortener configuration
    - Verification expiry windows
    - Verification token creation
    - Verification token validation
    - Shortener fallback
    - Async operation
"""

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shortzy import Shortzy

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

FIRST = 1
SECOND = 2
THIRD = 3

DEFAULT_VERIFY_GAP = 3600
TOKEN_LENGTH = 32

VALID_LAYERS = {
    FIRST,
    SECOND,
    THIRD,
}


# ============================================================================
# Data models
# ============================================================================

@dataclass
class ShortenerConfig:
    """
    Configuration for one shortener.
    """

    number: int
    website: Optional[str]
    api: Optional[str]
    verification_time: int = DEFAULT_VERIFY_GAP
    enabled: bool = True

    @property
    def configured(self) -> bool:
        return bool(
            self.website
            and self.api
        )


@dataclass
class VerificationToken:
    """
    Temporary verification token.
    """

    token: str
    user_id: int
    layer: int
    created_at: datetime
    expires_at: datetime
    verified: bool = False

    @property
    def expired(self) -> bool:
        return datetime.now(
            timezone.utc
        ) >= self.expires_at


@dataclass
class ShortenResult:
    """
    Result returned by the shortener.
    """

    success: bool
    original_url: str
    shortened_url: Optional[str] = None
    layer: Optional[int] = None
    error: Optional[str] = None


# ============================================================================
# Utility functions
# ============================================================================

def utcnow() -> datetime:
    """
    Return timezone-aware UTC time.
    """
    return datetime.now(
        timezone.utc
    )


def normalize_datetime(
    value: Any,
) -> Optional[datetime]:
    """
    Normalize MongoDB/Python datetime values.

    MongoDB commonly returns naive UTC datetimes depending on client
    configuration. Treat naive values as UTC.
    """
    if value is None:
        return None

    if not isinstance(
        value,
        datetime,
    ):
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def generate_token(
    length: int = TOKEN_LENGTH,
) -> str:
    """
    Generate a cryptographically strong verification token.
    """
    alphabet = (
        string.ascii_letters
        + string.digits
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


# ============================================================================
# Configuration adapter
# ============================================================================

class ShortenerManager:
    """
    Main shortener service.

    The manager intentionally depends on the database through a small
    interface rather than directly knowing MongoDB implementation details.

    Expected database methods:

        get_settings(group_id)
        get_notcopy_user(user_id)
        update_notcopy_user(user_id, value)
        create_verify_id(user_id, hash)
        get_verify_id_info(user_id, hash)
        update_verify_id_info(user_id, hash, value)
    """

    def __init__(
        self,
        db=None,
    ):
        self.db = db

    # ========================================================================
    # Database binding
    # ========================================================================

    def set_database(
        self,
        db,
    ) -> None:
        self.db = db

    def _require_database(self):
        if self.db is None:
            raise RuntimeError(
                "ShortenerManager database has not been configured"
            )

        return self.db

    # ========================================================================
    # Settings
    # ========================================================================

    async def get_group_settings(
        self,
        group_id: int,
    ) -> dict:
        """
        Load group settings from the application's database.
        """
        db = self._require_database()

        settings = await db.get_settings(
            int(group_id)
        )

        return settings or {}

    async def get_config(
        self,
        group_id: int,
        layer: int,
    ) -> ShortenerConfig:
        """
        Build a ShortenerConfig from the group's settings.
        """
        if layer not in VALID_LAYERS:
            raise ValueError(
                f"Invalid shortener layer: {layer}"
            )

        settings = await self.get_group_settings(
            group_id
        )

        if layer == FIRST:
            website_key = "shortner"
            api_key = "api"
            gap_key = "verify_time"

        elif layer == SECOND:
            website_key = "shortner_two"
            api_key = "api_two"
            gap_key = "verify_time"

        else:
            website_key = "shortner_three"
            api_key = "api_three"
            gap_key = "third_verify_time"

        website = settings.get(
            website_key
        )

        api = settings.get(
            api_key
        )

        gap = settings.get(
            gap_key,
            DEFAULT_VERIFY_GAP,
        )

        try:
            gap = int(gap)
        except (
            TypeError,
            ValueError,
        ):
            gap = DEFAULT_VERIFY_GAP

        enabled = True

        if layer == FIRST:
            enabled = bool(
                settings.get(
                    "is_verify",
                    True,
                )
            )

        return ShortenerConfig(
            number=layer,
            website=website,
            api=api,
            verification_time=max(
                0,
                gap,
            ),
            enabled=enabled,
        )

    # ========================================================================
    # Shortener selection
    # ========================================================================

    async def get_available_layers(
        self,
        group_id: int,
    ) -> list[int]:
        """
        Return configured shortener layers in order.
        """
        result = []

        for layer in (
            FIRST,
            SECOND,
            THIRD,
        ):
            try:
                config = await self.get_config(
                    group_id,
                    layer,
                )

                if (
                    config.enabled
                    and config.configured
                ):
                    result.append(
                        layer
                    )

            except Exception:
                logger.exception(
                    "Failed loading shortener layer %s",
                    layer,
                )

        return result

    async def get_next_layer(
        self,
        group_id: int,
        current_layer: int = 0,
    ) -> Optional[int]:
        """
        Get the next configured verification layer.
        """
        layers = await self.get_available_layers(
            group_id
        )

        for layer in layers:
            if layer > current_layer:
                return layer

        return None

    # ========================================================================
    # URL shortening
    # ========================================================================

    async def shorten(
        self,
        url: str,
        group_id: int,
        layer: int = FIRST,
    ) -> ShortenResult:
        """
        Shorten a URL using the requested shortener.
        """
        url = str(
            url or ""
        ).strip()

        if not url:
            return ShortenResult(
                success=False,
                original_url=url,
                layer=layer,
                error="empty_url",
            )

        try:
            config = await self.get_config(
                group_id,
                layer,
            )
        except Exception as exc:
            logger.exception(
                "Unable to load shortener configuration"
            )

            return ShortenResult(
                success=False,
                original_url=url,
                layer=layer,
                error=str(exc),
            )

        if not config.enabled:
            return ShortenResult(
                success=False,
                original_url=url,
                layer=layer,
                error="shortener_disabled",
            )

        if not config.configured:
            return ShortenResult(
                success=False,
                original_url=url,
                layer=layer,
                error="shortener_not_configured",
            )

        try:
            shortzy = Shortzy(
                config.api,
                config.website,
            )

            try:
                shortened = await shortzy.convert(
                    url
                )
            except Exception as first_error:
                logger.warning(
                    "Shortzy.convert failed for layer %s: %s",
                    layer,
                    first_error,
                )

                shortened = (
                    await shortzy.get_quick_link(
                        url
                    )
                )

            if not shortened:
                return ShortenResult(
                    success=False,
                    original_url=url,
                    layer=layer,
                    error="empty_shortener_response",
                )

            return ShortenResult(
                success=True,
                original_url=url,
                shortened_url=str(
                    shortened
                ),
                layer=layer,
            )

        except Exception as exc:
            logger.exception(
                "Shortener failed for layer %s",
                layer,
            )

            return ShortenResult(
                success=False,
                original_url=url,
                layer=layer,
                error=str(exc),
            )

    # ========================================================================
    # Fallback shortening
    # ========================================================================

    async def shorten_with_fallback(
        self,
        url: str,
        group_id: int,
        preferred_layer: int = FIRST,
    ) -> ShortenResult:
        """
        Try the requested layer first, then other configured layers.
        """
        layers = await self.get_available_layers(
            group_id
        )

        ordered = []

        if preferred_layer in layers:
            ordered.append(
                preferred_layer
            )

        for layer in layers:
            if layer not in ordered:
                ordered.append(
                    layer
                )

        if not ordered:
            return ShortenResult(
                success=False,
                original_url=url,
                error="no_shortener_configured",
            )

        last_result = None

        for layer in ordered:
            result = await self.shorten(
                url=url,
                group_id=group_id,
                layer=layer,
            )

            if result.success:
                return result

            last_result = result

        return last_result or ShortenResult(
            success=False,
            original_url=url,
            error="shortening_failed",
        )

    # ========================================================================
    # Verification records
    # ========================================================================

    async def create_verification(
        self,
        user_id: int,
        layer: int,
        verification_time: Optional[int] = None,
    ) -> VerificationToken:
        """
        Create a new verification record.

        This uses the existing verify_id collection from the old architecture.
        """
        if layer not in VALID_LAYERS:
            raise ValueError(
                "Invalid verification layer"
            )

        db = self._require_database()

        if verification_time is None:
            verification_time = DEFAULT_VERIFY_GAP

        verification_time = max(
            0,
            int(verification_time),
        )

        now = utcnow()

        token = generate_token()

        expires = (
            now
            + timedelta(
                seconds=verification_time
            )
        )

        await db.create_verify_id(
            int(user_id),
            token,
        )

        await db.update_verify_id_info(
            int(user_id),
            token,
            {
                "layer": layer,
                "verified": False,
                "created_at": now,
                "expires_at": expires,
            },
        )

        return VerificationToken(
            token=token,
            user_id=int(user_id),
            layer=layer,
            created_at=now,
            expires_at=expires,
        )

    async def get_verification(
        self,
        user_id: int,
        token: str,
    ) -> Optional[dict]:
        """
        Get a verification record.
        """
        db = self._require_database()

        return await db.get_verify_id_info(
            int(user_id),
            str(token),
        )

    async def mark_verified(
        self,
        user_id: int,
        token: str,
    ) -> bool:
        """
        Mark a verification token as completed.
        """
        record = await self.get_verification(
            user_id,
            token,
        )

        if not record:
            return False

        await self._require_database().update_verify_id_info(
            int(user_id),
            str(token),
            {
                "verified": True,
                "verified_at": utcnow(),
            },
        )

        return True

    # ========================================================================
    # Verification validation
    # ========================================================================

    async def validate_verification(
        self,
        user_id: int,
        token: str,
    ) -> tuple[bool, Optional[dict]]:
        """
        Validate a verification token.

        Returns:

            (True, record)

        or:

            (False, None)
        """
        record = await self.get_verification(
            user_id,
            token,
        )

        if not record:
            return False, None

        if record.get(
            "verified",
            False,
        ):
            return True, record

        expires_at = normalize_datetime(
            record.get(
                "expires_at"
            )
        )

        if expires_at:
            if utcnow() > expires_at:
                return False, record

        return True, record

    # ========================================================================
    # User verification state
    # ========================================================================

    async def get_user_state(
        self,
        user_id: int,
    ) -> dict:
        """
        Retrieve the old bot's verification state.
        """
        db = self._require_database()

        user = await db.get_notcopy_user(
            int(user_id)
        )

        return user or {}

    async def is_first_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Check first-level verification state.

        This preserves the old bot's daily verification model:
        a verification remains valid until the beginning of the next day.
        """
        user = await self.get_user_state(
            user_id
        )

        last_verified = normalize_datetime(
            user.get(
                "last_verified"
            )
        )

        if not last_verified:
            return False

        now = utcnow()

        return (
            last_verified.date()
            == now.date()
        )

    async def is_second_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Check second-level verification state.
        """
        user = await self.get_user_state(
            user_id
        )

        verified_at = normalize_datetime(
            user.get(
                "second_time_verified"
            )
        )

        if not verified_at:
            return False

        now = utcnow()

        return (
            verified_at.date()
            == now.date()
        )

    async def is_third_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Check third-level verification state.
        """
        user = await self.get_user_state(
            user_id
        )

        verified_at = normalize_datetime(
            user.get(
                "third_time_verified"
            )
        )

        if not verified_at:
            return False

        now = utcnow()

        return (
            verified_at.date()
            == now.date()
        )

    # ========================================================================
    # Verification timestamps
    # ========================================================================

    async def set_first_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Mark first verification as completed.
        """
        db = self._require_database()

        result = await db.update_notcopy_user(
            int(user_id),
            {
                "last_verified": utcnow()
            },
        )

        return bool(
            result
        )

    async def set_second_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Mark second verification as completed.
        """
        db = self._require_database()

        result = await db.update_notcopy_user(
            int(user_id),
            {
                "second_time_verified": utcnow()
            },
        )

        return bool(
            result
        )

    async def set_third_verified(
        self,
        user_id: int,
    ) -> bool:
        """
        Mark third verification as completed.
        """
        db = self._require_database()

        result = await db.update_notcopy_user(
            int(user_id),
            {
                "third_time_verified": utcnow()
            },
        )

        return bool(
            result
        )

    # ========================================================================
    # Verification requirements
    # ========================================================================

    async def requires_second_verification(
        self,
        user_id: int,
        group_id: int,
        required_after_seconds: Optional[int] = None,
    ) -> bool:
        """
        Determine whether the user needs second-level verification.

        The old bot's use_second_shortener() behavior is preserved conceptually:
        first verification must exist and enough time must have passed since it.
        """
        if not await self.is_first_verified(
            user_id
        ):
            return False

        if await self.is_second_verified(
            user_id
        ):
            return False

        if required_after_seconds is None:
            config = await self.get_config(
                group_id,
                SECOND,
            )

            required_after_seconds = (
                config.verification_time
            )

        user = await self.get_user_state(
            user_id
        )

        first_verified = normalize_datetime(
            user.get(
                "last_verified"
            )
        )

        if not first_verified:
            return False

        elapsed = (
            utcnow()
            - first_verified
        ).total_seconds()

        return (
            elapsed
            > int(required_after_seconds)
        )

    async def requires_third_verification(
        self,
        user_id: int,
        group_id: int,
        required_after_seconds: Optional[int] = None,
    ) -> bool:
        """
        Determine whether third-level verification is required.
        """
        if not await self.is_second_verified(
            user_id
        ):
            return False

        if await self.is_third_verified(
            user_id
        ):
            return False

        if required_after_seconds is None:
            config = await self.get_config(
                group_id,
                THIRD,
            )

            required_after_seconds = (
                config.verification_time
            )

        user = await self.get_user_state(
            user_id
        )

        second_verified = normalize_datetime(
            user.get(
                "second_time_verified"
            )
        )

        if not second_verified:
            return False

        elapsed = (
            utcnow()
            - second_verified
        ).total_seconds()

        return (
            elapsed
            > int(required_after_seconds)
        )

    # ========================================================================
    # Complete verification flow
    # ========================================================================

    async def verify_user(
        self,
        user_id: int,
        layer: int,
    ) -> bool:
        """
        Complete verification for a particular layer.
        """
        if layer == FIRST:
            return await self.set_first_verified(
                user_id
            )

        if layer == SECOND:
            return await self.set_second_verified(
                user_id
            )

        if layer == THIRD:
            return await self.set_third_verified(
                user_id
            )

        return False

    # ========================================================================
    # Build verification URL
    # ========================================================================

    async def build_verification(
        self,
        original_url: str,
        user_id: int,
        group_id: int,
        layer: int,
        callback_base_url: str,
    ) -> Optional[dict]:
        """
        Create a shortener URL and corresponding verification token.

        The application can later expose a handler such as:

            /verify <token>

        or:

            /start verify_<token>

        without the shortener service needing to know the handler details.
        """
        config = await self.get_config(
            group_id,
            layer,
        )

        if not config.enabled:
            return None

        if not config.configured:
            return None

        verification = await self.create_verification(
            user_id=user_id,
            layer=layer,
            verification_time=config.verification_time,
        )

        callback_base_url = (
            str(callback_base_url)
            .rstrip("/")
        )

        verification_url = (
            f"{callback_base_url}"
            f"?verify={verification.token}"
            f"&user={int(user_id)}"
            f"&layer={layer}"
        )

        result = await self.shorten(
            url=verification_url,
            group_id=group_id,
            layer=layer,
        )

        if not result.success:
            return None

        return {
            "token": verification.token,
            "layer": layer,
            "verification_url": verification_url,
            "shortened_url": result.shortened_url,
            "expires_at": verification.expires_at,
            "original_url": original_url,
        }

    # ========================================================================
    # Sequential verification
    # ========================================================================

    async def get_required_layer(
        self,
        user_id: int,
        group_id: int,
    ) -> Optional[int]:
        """
        Determine which verification layer should be requested next.

        Order:

            1 -> 2 -> 3
        """
        layers = await self.get_available_layers(
            group_id
        )

        if not layers:
            return None

        if FIRST in layers:
            if not await self.is_first_verified(
                user_id
            ):
                return FIRST

        if SECOND in layers:
            if await self.requires_second_verification(
                user_id,
                group_id,
            ):
                return SECOND

        if THIRD in layers:
            if await self.requires_third_verification(
                user_id,
                group_id,
            ):
                return THIRD

        return None

    # ========================================================================
    # Complete access decision
    # ========================================================================

    async def check_access(
        self,
        user_id: int,
        group_id: int,
    ) -> dict:
        """
        Return the current verification/access state.

        Example:

            {
                "allowed": False,
                "required_layer": 2,
                "verified_layers": [1],
            }
        """
        layers = await self.get_available_layers(
            group_id
        )

        verified_layers = []

        if (
            FIRST in layers
            and await self.is_first_verified(
                user_id
            )
        ):
            verified_layers.append(
                FIRST
            )

        if (
            SECOND in layers
            and await self.is_second_verified(
                user_id
            )
        ):
            verified_layers.append(
                SECOND
            )

        if (
            THIRD in layers
            and await self.is_third_verified(
                user_id
            )
        ):
            verified_layers.append(
                THIRD
            )

        required_layer = (
            await self.get_required_layer(
                user_id,
                group_id,
            )
        )

        return {
            "allowed": (
                required_layer is None
            ),
            "required_layer": required_layer,
            "verified_layers": verified_layers,
            "available_layers": layers,
        }


# ============================================================================
# Module-level manager
# ============================================================================

shortener = ShortenerManager()


# ============================================================================
# Database initialization helper
# ============================================================================

def initialize_shortener(
    db,
) -> ShortenerManager:
    """
    Bind the application's database to the global shortener service.

    Call once during application startup:

        initialize_shortener(db)
    """
    shortener.set_database(
        db
    )

    return shortener


# ============================================================================
# Compatibility functions
# ============================================================================

async def get_shortlink(
    link: str,
    group_id: int,
    is_second_shortener: bool = False,
    is_third_shortener: bool = False,
) -> str:
    """
    Compatibility replacement for the old utils.get_shortlink().

    Returns the shortened URL or the original URL when shortening fails.
    """
    if is_third_shortener:
        layer = THIRD

    elif is_second_shortener:
        layer = SECOND

    else:
        layer = FIRST

    result = await shortener.shorten(
        url=link,
        group_id=group_id,
        layer=layer,
    )

    if result.success:
        return result.shortened_url

    logger.warning(
        "Shortening failed; returning original URL"
    )

    return link


async def get_next_shortener(
    group_id: int,
    current_layer: int = 0,
) -> Optional[int]:
    """
    Compatibility helper.
    """
    return await shortener.get_next_layer(
        group_id,
        current_layer,
    )


async def create_verification(
    user_id: int,
    group_id: int,
    layer: int,
) -> VerificationToken:
    """
    Create a verification record using group configuration.
    """
    config = await shortener.get_config(
        group_id,
        layer,
    )

    return await shortener.create_verification(
        user_id=user_id,
        layer=layer,
        verification_time=config.verification_time,
    )


async def verify_user(
    user_id: int,
    layer: int,
) -> bool:
    """
    Compatibility helper for completing verification.
    """
    return await shortener.verify_user(
        user_id,
        layer,
    )


async def check_verification(
    user_id: int,
    group_id: int,
) -> dict:
    """
    Compatibility helper returning access state.
    """
    return await shortener.check_access(
        user_id,
        group_id,
    )


__all__ = [
    "FIRST",
    "SECOND",
    "THIRD",
    "ShortenerConfig",
    "VerificationToken",
    "ShortenResult",
    "ShortenerManager",
    "shortener",
    "initialize_shortener",
    "get_shortlink",
    "get_next_shortener",
    "create_verification",
    "verify_user",
    "check_verification",
]