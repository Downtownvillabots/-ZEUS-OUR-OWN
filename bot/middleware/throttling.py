"""
bot.middleware.throttling

In-memory rate limiting middleware.

Protects the bot against:
    - Command spam
    - Callback spam
    - Message flooding
    - Accidental duplicate requests

The implementation uses a token-bucket-like sliding-window strategy.

For a multi-instance deployment, replace the storage backend with Redis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

@dataclass(slots=True)
class RateLimitConfig:

    max_requests: int = 10

    window_seconds: float = 5.0

    burst: int = 3

    cleanup_interval: float = 60.0

    block_seconds: float = 0.0


# ============================================================================
# Rate limiter
# ============================================================================

class RateLimiter:

    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
    ) -> None:

        self.config = (
            config
            or RateLimitConfig()
        )

        if self.config.max_requests <= 0:
            raise ValueError(
                "max_requests must be greater than zero."
            )

        if self.config.window_seconds <= 0:
            raise ValueError(
                "window_seconds must be greater than zero."
            )

        self._requests: dict[
            str,
            deque[float],
        ] = defaultdict(
            deque
        )

        self._blocked_until: dict[
            str,
            float,
        ] = {}

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Key
    # ------------------------------------------------------------------

    @staticmethod
    def make_key(
        update: Update,
        *,
        scope: str = "user",
    ) -> Optional[str]:

        user = update.effective_user

        if scope == "global":
            return "global"

        if scope == "chat":

            chat = update.effective_chat

            if chat is None:
                return None

            return f"chat:{chat.id}"

        if user is None:
            return None

        return f"user:{user.id}"

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup_key(
        self,
        key: str,
        now: float,
    ) -> None:

        history = self._requests.get(
            key
        )

        if history is None:
            return

        cutoff = (
            now
            - self.config.window_seconds
        )

        while history and history[0] <= cutoff:
            history.popleft()

        if not history:
            self._requests.pop(
                key,
                None,
            )

    def cleanup(self) -> None:

        now = time.monotonic()

        keys = list(
            self._requests.keys()
        )

        for key in keys:
            self._cleanup_key(
                key,
                now,
            )

        blocked_keys = list(
            self._blocked_until.keys()
        )

        for key in blocked_keys:

            if (
                self._blocked_until[key]
                <= now
            ):

                self._blocked_until.pop(
                    key,
                    None,
                )

    # ------------------------------------------------------------------
    # Check
    # ------------------------------------------------------------------

    async def check(
        self,
        key: str,
    ) -> tuple[bool, float]:

        now = time.monotonic()

        async with self._lock:

            blocked_until = (
                self._blocked_until.get(
                    key,
                    0.0,
                )
            )

            if blocked_until > now:

                return (
                    False,
                    blocked_until - now,
                )

            self._cleanup_key(
                key,
                now,
            )

            history = self._requests[key]

            limit = (
                self.config.max_requests
                + max(
                    0,
                    self.config.burst,
                )
            )

            if len(history) >= limit:

                retry_after = (
                    history[0]
                    + self.config.window_seconds
                    - now
                )

                if (
                    self.config.block_seconds
                    > 0
                ):

                    self._blocked_until[
                        key
                    ] = (
                        now
                        + self.config.block_seconds
                    )

                return (
                    False,
                    max(
                        0.0,
                        retry_after,
                    ),
                )

            history.append(
                now
            )

            return (
                True,
                0.0,
            )

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    async def reset(
        self,
        key: str,
    ) -> None:

        async with self._lock:

            self._requests.pop(
                key,
                None,
            )

            self._blocked_until.pop(
                key,
                None,
            )

    async def reset_all(self) -> None:

        async with self._lock:

            self._requests.clear()
            self._blocked_until.clear()


# ============================================================================
# Middleware
# ============================================================================

class ThrottlingMiddleware:

    def __init__(
        self,
        limiter: Optional[RateLimiter] = None,
        *,
        config: Optional[RateLimitConfig] = None,
        scope: str = "user",
        exempt_user_ids: Optional[
            set[int]
        ] = None,
        on_limited: Optional[
            Callable[
                [Update, ContextTypes.DEFAULT_TYPE, float],
                Any,
            ]
        ] = None,
    ) -> None:

        self.limiter = (
            limiter
            or RateLimiter(config)
        )

        self.scope = scope

        self.exempt_user_ids = {
            int(user_id)
            for user_id in (
                exempt_user_ids or set()
            )
        }

        self.on_limited = on_limited

    # ------------------------------------------------------------------
    # Exemption
    # ------------------------------------------------------------------

    def is_exempt(
        self,
        update: Update,
    ) -> bool:

        user = update.effective_user

        if user is None:
            return False

        return int(
            user.id
        ) in self.exempt_user_ids

    # ------------------------------------------------------------------
    # Process
    # ------------------------------------------------------------------

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        if self.is_exempt(update):

            context.user_data[
                "rate_limited"
            ] = False

            return True

        key = self.limiter.make_key(
            update,
            scope=self.scope,
        )

        if key is None:

            context.user_data[
                "rate_limited"
            ] = False

            return True

        allowed, retry_after = (
            await self.limiter.check(key)
        )

        context.user_data[
            "rate_limited"
        ] = not allowed

        context.user_data[
            "rate_limit_retry_after"
        ] = retry_after

        if allowed:
            return True

        logger.warning(
            "Rate limit exceeded: key=%s retry_after=%.2f",
            key,
            retry_after,
        )

        if self.on_limited is not None:

            try:

                result = self.on_limited(
                    update,
                    context,
                    retry_after,
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    await result

            except Exception:

                logger.exception(
                    "Rate-limit callback failed."
                )

        return False

    async def __call__(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        return await self.process(
            update,
            context,
        )


# ============================================================================
# Presets
# ============================================================================

def create_default_limiter() -> RateLimiter:

    return RateLimiter(
        RateLimitConfig(
            max_requests=10,
            window_seconds=5.0,
            burst=3,
            block_seconds=2.0,
        )
    )


def create_search_limiter() -> RateLimiter:

    return RateLimiter(
        RateLimitConfig(
            max_requests=5,
            window_seconds=10.0,
            burst=2,
            block_seconds=5.0,
        )
    )


def create_delivery_limiter() -> RateLimiter:

    return RateLimiter(
        RateLimitConfig(
            max_requests=3,
            window_seconds=30.0,
            burst=1,
            block_seconds=10.0,
        )
    )


__all__ = [
    "RateLimitConfig",
    "RateLimiter",
    "ThrottlingMiddleware",
    "create_default_limiter",
    "create_search_limiter",
    "create_delivery_limiter",
]