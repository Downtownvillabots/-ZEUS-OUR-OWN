"""
bot.middleware.rate_limit

Application rate-limiting middleware.

Features
--------
- Per-user limits
- Per-chat limits
- Per-action limits
- Sliding-window counters
- Separate burst and sustained limits
- Admin bypass
- Automatic cleanup
- Retry-after calculation
- Async-safe locking
- In-memory backend by default
- Optional Redis-compatible backend adapter
- MiddlewareContext integration

Design
------
The middleware is intentionally independent of the database.

Rate limits are temporary runtime state and should normally live in
Redis for multi-instance deployments. The in-memory backend is suitable
for a single-process deployment and development.

Example callback/action keys:

    search
    file_search
    download
    movie
    settings
    verification
    broadcast

Recommended production limits:

    global/user:
        30 requests / 60 seconds

    search:
        10 requests / 30 seconds

    file download:
        20 requests / 60 seconds

    expensive search:
        5 requests / 60 seconds
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

from pyrogram import Client
from pyrogram.types import CallbackQuery, Message

from bot.middleware import MiddlewareContext

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

RATE_LIMIT_CONTEXT_KEY = "rate_limit"

RATE_LIMIT_BLOCKED_KEY = (
    "rate_limit_blocked"
)

RATE_LIMIT_RETRY_AFTER_KEY = (
    "rate_limit_retry_after"
)

DEFAULT_WINDOW_SECONDS = 60.0

DEFAULT_MAX_REQUESTS = 30

DEFAULT_BURST_WINDOW_SECONDS = 5.0

DEFAULT_BURST_REQUESTS = 8

CLEANUP_INTERVAL = 60.0

MAX_TRACKED_KEYS = 100_000


# ============================================================================
# Data models
# ============================================================================

@dataclass(frozen=True)
class RateLimitRule:
    """
    One rate-limit rule.

    Example:

        RateLimitRule(
            name="search",
            limit=10,
            window=30,
        )
    """

    name: str

    limit: int

    window: float

    burst_limit: Optional[int] = None

    burst_window: Optional[float] = None

    enabled: bool = True

    admin_bypass: bool = True

    message: Optional[str] = None

    def __post_init__(self):

        if self.limit <= 0:

            raise ValueError(
                "Rate limit must be greater than zero."
            )

        if self.window <= 0:

            raise ValueError(
                "Rate-limit window must be greater than zero."
            )

        if (
            self.burst_limit is not None
            and self.burst_limit <= 0
        ):

            raise ValueError(
                "Burst limit must be greater than zero."
            )

        if (
            self.burst_window is not None
            and self.burst_window <= 0
        ):

            raise ValueError(
                "Burst window must be greater than zero."
            )


@dataclass
class RateLimitResult:
    """
    Result returned after checking a rate limit.
    """

    allowed: bool

    key: str

    rule: str

    limit: int

    remaining: int

    retry_after: float = 0.0

    window: float = DEFAULT_WINDOW_SECONDS

    burst_limited: bool = False

    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:

        return {
            "allowed": self.allowed,
            "key": self.key,
            "rule": self.rule,
            "limit": self.limit,
            "remaining": self.remaining,
            "retry_after": self.retry_after,
            "window": self.window,
            "burst_limited": self.burst_limited,
            "reason": self.reason,
        }


@dataclass
class Bucket:
    """
    Sliding-window timestamp bucket.
    """

    timestamps: deque[float] = field(
        default_factory=deque
    )

    last_access: float = field(
        default_factory=time.monotonic
    )


# ============================================================================
# Default rules
# ============================================================================

DEFAULT_RULES: tuple[
    RateLimitRule,
    ...
] = (
    RateLimitRule(
        name="global",
        limit=30,
        window=60,
        burst_limit=8,
        burst_window=5,
    ),
    RateLimitRule(
        name="search",
        limit=10,
        window=30,
        burst_limit=4,
        burst_window=5,
    ),
    RateLimitRule(
        name="file_search",
        limit=10,
        window=30,
        burst_limit=4,
        burst_window=5,
    ),
    RateLimitRule(
        name="download",
        limit=20,
        window=60,
        burst_limit=5,
        burst_window=5,
    ),
    RateLimitRule(
        name="movie",
        limit=10,
        window=60,
        burst_limit=3,
        burst_window=5,
    ),
    RateLimitRule(
        name="verification",
        limit=10,
        window=60,
        burst_limit=3,
        burst_window=5,
    ),
    RateLimitRule(
        name="settings",
        limit=30,
        window=60,
        burst_limit=8,
        burst_window=5,
    ),
    RateLimitRule(
        name="premium",
        limit=20,
        window=60,
        burst_limit=6,
        burst_window=5,
    ),
    RateLimitRule(
        name="broadcast",
        limit=5,
        window=60,
        burst_limit=2,
        burst_window=10,
    ),
)


# ============================================================================
# Helpers
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


def get_chat_id(
    update: Any,
) -> Optional[int]:

    message = getattr(
        update,
        "message",
        None,
    )

    if message is not None:

        chat = getattr(
            message,
            "chat",
            None,
        )

        if chat is not None:

            try:

                return int(
                    chat.id
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

    chat = getattr(
        update,
        "chat",
        None,
    )

    if chat is not None:

        try:

            return int(
                chat.id
            )

        except (
            TypeError,
            ValueError,
        ):

            pass

    return None


def get_action(
    update: Any,
) -> str:

    data = getattr(
        update,
        "data",
        None,
    )

    if data:

        parts = str(
            data
        ).split(":")

        if len(parts) >= 2:

            return (
                f"{parts[0]}:{parts[1]}"
            )

        return parts[0]

    command = getattr(
        update,
        "command",
        None,
    )

    if command:

        try:

            return str(
                command[0]
            ).lower()

        except (
            IndexError,
            TypeError,
        ):

            pass

    return "message"


def normalize_action(
    action: Optional[str],
) -> str:

    if not action:
        return "global"

    return (
        str(action)
        .strip()
        .lower()
        .replace(" ", "_")
    )


def format_seconds(
    seconds: float,
) -> str:

    seconds = max(
        0,
        int(
            seconds + 0.999
        ),
    )

    if seconds < 60:

        return f"{seconds}s"

    minutes, remaining = divmod(
        seconds,
        60,
    )

    if minutes < 60:

        if remaining:

            return (
                f"{minutes}m "
                f"{remaining}s"
            )

        return f"{minutes}m"

    hours, minutes = divmod(
        minutes,
        60,
    )

    if minutes:

        return (
            f"{hours}h "
            f"{minutes}m"
        )

    return f"{hours}h"


# ============================================================================
# In-memory backend
# ============================================================================

class InMemoryRateLimitBackend:
    """
    Sliding-window in-memory rate-limit backend.

    Suitable for:
        - development
        - tests
        - one-process deployments

    Not suitable for:
        - horizontally scaled workers
        - multiple bot processes

    For those deployments use Redis.
    """

    def __init__(
        self,
        *,
        cleanup_interval: float = CLEANUP_INTERVAL,
        max_keys: int = MAX_TRACKED_KEYS,
    ) -> None:

        self.cleanup_interval = float(
            cleanup_interval
        )

        self.max_keys = int(
            max_keys
        )

        self._buckets: dict[
            str,
            Bucket,
        ] = {}

        self._lock = asyncio.Lock()

        self._last_cleanup = (
            time.monotonic()
        )

    # ------------------------------------------------------------------------
    # Internal cleanup
    # ------------------------------------------------------------------------

    def _cleanup_expired(
        self,
        now: float,
        window: float,
    ) -> None:

        cutoff = (
            now - window
        )

        expired_keys = []

        for key, bucket in self._buckets.items():

            timestamps = (
                bucket.timestamps
            )

            while (
                timestamps
                and timestamps[0] <= cutoff
            ):

                timestamps.popleft()

            if not timestamps:

                expired_keys.append(
                    key
                )

        for key in expired_keys:

            self._buckets.pop(
                key,
                None,
            )

    async def cleanup(
        self,
        *,
        window: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:

        async with self._lock:

            now = time.monotonic()

            self._cleanup_expired(
                now,
                window,
            )

            self._last_cleanup = now

    # ------------------------------------------------------------------------
    # Bucket
    # ------------------------------------------------------------------------

    async def get_bucket(
        self,
        key: str,
    ) -> Bucket:

        async with self._lock:

            bucket = self._buckets.get(
                key
            )

            if bucket is None:

                if (
                    len(self._buckets)
                    >= self.max_keys
                ):

                    self._evict_oldest()

                bucket = Bucket()

                self._buckets[
                    key
                ] = bucket

            bucket.last_access = (
                time.monotonic()
            )

            return bucket

    def _evict_oldest(
        self,
    ) -> None:

        if not self._buckets:
            return

        oldest_key = min(
            self._buckets,
            key=lambda key:
                self._buckets[
                    key
                ].last_access,
        )

        self._buckets.pop(
            oldest_key,
            None,
        )

    # ------------------------------------------------------------------------
    # Sliding-window check
    # ------------------------------------------------------------------------

    async def check(
        self,
        key: str,
        *,
        limit: int,
        window: float,
        consume: bool = True,
    ) -> RateLimitResult:

        now = time.monotonic()

        async with self._lock:

            bucket = self._buckets.get(
                key
            )

            if bucket is None:

                if (
                    len(self._buckets)
                    >= self.max_keys
                ):

                    self._evict_oldest()

                bucket = Bucket()

                self._buckets[
                    key
                ] = bucket

            timestamps = (
                bucket.timestamps
            )

            cutoff = (
                now - window
            )

            while (
                timestamps
                and timestamps[0] <= cutoff
            ):

                timestamps.popleft()

            count = len(
                timestamps
            )

            if count >= limit:

                retry_after = (
                    timestamps[0]
                    + window
                    - now
                )

                return RateLimitResult(
                    allowed=False,
                    key=key,
                    rule="",
                    limit=limit,
                    remaining=0,
                    retry_after=max(
                        0,
                        retry_after,
                    ),
                    window=window,
                )

            if consume:

                timestamps.append(
                    now
                )

            bucket.last_access = now

            return RateLimitResult(
                allowed=True,
                key=key,
                rule="",
                limit=limit,
                remaining=max(
                    0,
                    limit - count - (
                        1
                        if consume
                        else 0
                    ),
                ),
                retry_after=0,
                window=window,
            )

    # ------------------------------------------------------------------------
    # Burst support
    # ------------------------------------------------------------------------

    async def check_dual_window(
        self,
        key: str,
        rule: RateLimitRule,
        *,
        consume: bool = True,
    ) -> RateLimitResult:

        now = time.monotonic()

        async with self._lock:

            bucket = self._buckets.get(
                key
            )

            if bucket is None:

                if (
                    len(self._buckets)
                    >= self.max_keys
                ):

                    self._evict_oldest()

                bucket = Bucket()

                self._buckets[
                    key
                ] = bucket

            timestamps = (
                bucket.timestamps
            )

            long_cutoff = (
                now - rule.window
            )

            while (
                timestamps
                and timestamps[0] <= long_cutoff
            ):

                timestamps.popleft()

            count = len(
                timestamps
            )

            if count >= rule.limit:

                retry_after = (
                    timestamps[0]
                    + rule.window
                    - now
                )

                return RateLimitResult(
                    allowed=False,
                    key=key,
                    rule=rule.name,
                    limit=rule.limit,
                    remaining=0,
                    retry_after=max(
                        0,
                        retry_after,
                    ),
                    window=rule.window,
                    burst_limited=False,
                    reason="window",
                )

            # Burst check.
            if (
                rule.burst_limit is not None
                and rule.burst_window is not None
            ):

                burst_cutoff = (
                    now
                    - rule.burst_window
                )

                burst_count = 0

                for timestamp in reversed(
                    timestamps
                ):

                    if (
                        timestamp
                        <= burst_cutoff
                    ):
                        break

                    burst_count += 1

                if (
                    burst_count
                    >= rule.burst_limit
                ):

                    retry_after = (
                        timestamps[
                            max(
                                0,
                                len(
                                    timestamps
                                )
                                - burst_count,
                            )
                        ]
                        + rule.burst_window
                        - now
                    )

                    return RateLimitResult(
                        allowed=False,
                        key=key,
                        rule=rule.name,
                        limit=rule.limit,
                        remaining=max(
                            0,
                            rule.limit
                            - count,
                        ),
                        retry_after=max(
                            0,
                            retry_after,
                        ),
                        window=rule.burst_window,
                        burst_limited=True,
                        reason="burst",
                    )

            if consume:

                timestamps.append(
                    now
                )

            bucket.last_access = now

            return RateLimitResult(
                allowed=True,
                key=key,
                rule=rule.name,
                limit=rule.limit,
                remaining=max(
                    0,
                    rule.limit
                    - count
                    - (
                        1
                        if consume
                        else 0
                    ),
                ),
                retry_after=0,
                window=rule.window,
            )

    async def reset(
        self,
        key: str,
    ) -> None:

        async with self._lock:

            self._buckets.pop(
                key,
                None,
            )

    async def reset_all(
        self,
    ) -> None:

        async with self._lock:

            self._buckets.clear()

    async def size(
        self,
    ) -> int:

        async with self._lock:

            return len(
                self._buckets
            )


# ============================================================================
# Redis backend
# ============================================================================

class RedisRateLimitBackend:
    """
    Redis-compatible sliding-window backend.

    Requires an async Redis client exposing:

        pipeline()
        zremrangebyscore()
        zcard()
        zadd()
        expire()
        execute()

    The backend is intentionally dependency-free and accepts an existing
    Redis client from the application.
    """

    def __init__(
        self,
        redis: Any,
        *,
        prefix: str = "bot:ratelimit",
    ) -> None:

        self.redis = redis

        self.prefix = prefix.rstrip(
            ":"
        )

    def make_key(
        self,
        key: str,
    ) -> str:

        return (
            f"{self.prefix}:{key}"
        )

    async def check(
        self,
        key: str,
        *,
        limit: int,
        window: float,
        rule_name: str = "",
        consume: bool = True,
    ) -> RateLimitResult:

        now = time.time()

        redis_key = self.make_key(
            key
        )

        pipeline = self.redis.pipeline(
            transaction=True
        )

        cutoff = (
            now - window
        )

        pipeline.zremrangebyscore(
            redis_key,
            0,
            cutoff,
        )

        pipeline.zcard(
            redis_key
        )

        if consume:

            pipeline.zadd(
                redis_key,
                {
                    f"{now}:{id(self)}": now
                },
            )

        pipeline.expire(
            redis_key,
            max(
                1,
                int(
                    window + 2
                ),
            ),
        )

        results = await pipeline.execute()

        # zcard is the second command.
        count = int(
            results[1]
            or 0
        )

        if count >= limit:

            return RateLimitResult(
                allowed=False,
                key=key,
                rule=rule_name,
                limit=limit,
                remaining=0,
                retry_after=window,
                window=window,
            )

        return RateLimitResult(
            allowed=True,
            key=key,
            rule=rule_name,
            limit=limit,
            remaining=max(
                0,
                limit
                - count
                - (
                    1
                    if consume
                    else 0
                ),
            ),
            retry_after=0,
            window=window,
        )


# ============================================================================
# Rate limiter
# ============================================================================

class RateLimiter:
    """
    Main rate limiter.

    The limiter supports:
        - user scope
        - chat scope
        - action scope
        - global/user combined checks
    """

    def __init__(
        self,
        backend: Optional[Any] = None,
        rules: Optional[
            list[RateLimitRule]
            | tuple[RateLimitRule, ...]
        ] = None,
    ) -> None:

        self.backend = (
            backend
            or InMemoryRateLimitBackend()
        )

        self.rules: dict[
            str,
            RateLimitRule,
        ] = {}

        for rule in (
            rules
            or DEFAULT_RULES
        ):

            self.add_rule(
                rule
            )

    # ------------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------------

    def add_rule(
        self,
        rule: RateLimitRule,
    ) -> None:

        self.rules[
            rule.name.lower()
        ] = rule

    def remove_rule(
        self,
        name: str,
    ) -> None:

        self.rules.pop(
            str(name)
            .strip()
            .lower(),
            None,
        )

    def get_rule(
        self,
        name: str,
    ) -> Optional[RateLimitRule]:

        return self.rules.get(
            normalize_action(
                name
            )
        )

    def has_rule(
        self,
        name: str,
    ) -> bool:

        return (
            self.get_rule(
                name
            )
            is not None
        )

    # ------------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------------

    @staticmethod
    def user_key(
        user_id: int,
        rule: str,
    ) -> str:

        return (
            f"user:{int(user_id)}:"
            f"{normalize_action(rule)}"
        )

    @staticmethod
    def chat_key(
        chat_id: int,
        rule: str,
    ) -> str:

        return (
            f"chat:{int(chat_id)}:"
            f"{normalize_action(rule)}"
        )

    @staticmethod
    def global_key(
        rule: str,
    ) -> str:

        return (
            f"global:{normalize_action(rule)}"
        )

    # ------------------------------------------------------------------------
    # Rule checking
    # ------------------------------------------------------------------------

    async def check(
        self,
        *,
        user_id: Optional[int],
        chat_id: Optional[int],
        action: str = "global",
        is_admin: bool = False,
        consume: bool = True,
    ) -> RateLimitResult:

        action = normalize_action(
            action
        )

        rule = (
            self.get_rule(
                action
            )
            or self.get_rule(
                "global"
            )
        )

        if rule is None:

            return RateLimitResult(
                allowed=True,
                key="none",
                rule=action,
                limit=0,
                remaining=0,
            )

        if (
            is_admin
            and rule.admin_bypass
        ):

            return RateLimitResult(
                allowed=True,
                key="admin",
                rule=rule.name,
                limit=rule.limit,
                remaining=rule.limit,
            )

        if not rule.enabled:

            return RateLimitResult(
                allowed=True,
                key="disabled",
                rule=rule.name,
                limit=rule.limit,
                remaining=rule.limit,
            )

        # ---------------------------------------------------------------
        # User scope
        # ---------------------------------------------------------------

        if user_id is not None:

            user_key = self.user_key(
                user_id,
                rule.name,
            )

            result = await self._check_backend(
                user_key,
                rule,
                consume=consume,
            )

            result.rule = rule.name

            if not result.allowed:

                return result

        # ---------------------------------------------------------------
        # Chat scope
        # ---------------------------------------------------------------

        if chat_id is not None:

            chat_key = self.chat_key(
                chat_id,
                rule.name,
            )

            result = await self._check_backend(
                chat_key,
                rule,
                consume=consume,
            )

            result.rule = rule.name

            if not result.allowed:

                return result

        return RateLimitResult(
            allowed=True,
            key=(
                self.user_key(
                    user_id,
                    rule.name,
                )
                if user_id is not None
                else self.global_key(
                    rule.name
                )
            ),
            rule=rule.name,
            limit=rule.limit,
            remaining=result.remaining
            if (
                "result" in locals()
            )
            else rule.limit,
            window=rule.window,
        )

    async def _check_backend(
        self,
        key: str,
        rule: RateLimitRule,
        *,
        consume: bool,
    ) -> RateLimitResult:

        if isinstance(
            self.backend,
            InMemoryRateLimitBackend,
        ):

            return await self.backend.check_dual_window(
                key,
                rule,
                consume=consume,
            )

        if isinstance(
            self.backend,
            RedisRateLimitBackend,
        ):

            return await self.backend.check(
                key,
                limit=rule.limit,
                window=rule.window,
                rule_name=rule.name,
                consume=consume,
            )

        # Generic backend support.
        check_method = getattr(
            self.backend,
            "check",
            None,
        )

        if check_method is None:

            raise RuntimeError(
                "Rate-limit backend does not implement check()."
            )

        result = check_method(
            key,
            limit=rule.limit,
            window=rule.window,
            consume=consume,
        )

        if hasattr(
            result,
            "__await__",
        ):

            result = await result

        if isinstance(
            result,
            RateLimitResult,
        ):

            return result

        return RateLimitResult(
            allowed=bool(
                result
            ),
            key=key,
            rule=rule.name,
            limit=rule.limit,
            remaining=(
                rule.limit
                if result
                else 0
            ),
        )

    # ------------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------------

    async def reset_user(
        self,
        user_id: int,
        action: Optional[str] = None,
    ) -> None:

        if not hasattr(
            self.backend,
            "reset",
        ):
            return

        if action:

            rule = (
                self.get_rule(
                    action
                )
                or self.get_rule(
                    "global"
                )
            )

            await self.backend.reset(
                self.user_key(
                    user_id,
                    rule.name,
                )
            )

            return

        for rule in self.rules.values():

            await self.backend.reset(
                self.user_key(
                    user_id,
                    rule.name,
                )
            )

    async def reset_chat(
        self,
        chat_id: int,
        action: Optional[str] = None,
    ) -> None:

        if not hasattr(
            self.backend,
            "reset",
        ):
            return

        if action:

            rule = (
                self.get_rule(
                    action
                )
                or self.get_rule(
                    "global"
                )
            )

            await self.backend.reset(
                self.chat_key(
                    chat_id,
                    rule.name,
                )
            )

            return

        for rule in self.rules.values():

            await self.backend.reset(
                self.chat_key(
                    chat_id,
                    rule.name,
                )
            )

    # ------------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------------

    def list_rules(
        self,
    ) -> list[RateLimitRule]:

        return list(
            self.rules.values()
        )


# ============================================================================
# User-facing response
# ============================================================================

def build_rate_limit_message(
    result: RateLimitResult,
) -> str:

    retry = format_seconds(
        result.retry_after
    )

    if result.burst_limited:

        return (
            "⚡ <b>Slow down a little.</b>\n\n"
            "You're sending requests too quickly.\n"
            f"Please wait about <b>{retry}</b>."
        )

    return (
        "⏳ <b>Rate limit reached</b>\n\n"
        f"Please wait about <b>{retry}</b> "
        "before trying again."
    )


async def send_rate_limit_message(
    update: Any,
    result: RateLimitResult,
) -> bool:

    text = build_rate_limit_message(
        result
    )

    if isinstance(
        update,
        CallbackQuery,
    ):

        try:

            await update.answer(
                text,
                show_alert=True,
            )

            return True

        except Exception:

            logger.debug(
                "Unable to answer rate-limit callback.",
                exc_info=True,
            )

            return False

    if isinstance(
        update,
        Message,
    ):

        try:

            await update.reply_text(
                text
            )

            return True

        except Exception:

            logger.debug(
                "Unable to send rate-limit message.",
                exc_info=True,
            )

            return False

    return False


# ============================================================================
# Middleware
# ============================================================================

class RateLimitMiddleware:
    """
    Rate-limit middleware.

    It checks:
        1. Action-specific user limit
        2. Action-specific chat limit

    Administrators can bypass configured limits.
    """

    def __init__(
        self,
        limiter: Optional[RateLimiter] = None,
        *,
        allow_admins: bool = True,
    ) -> None:

        self.limiter = (
            limiter
            or RateLimiter()
        )

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

        user_id = (
            context.user_id
            or get_user_id(
                update
            )
        )

        chat_id = (
            context.chat_id
            or get_chat_id(
                update
            )
        )

        action = get_action(
            update
        )

        is_admin = bool(
            context.is_admin
        )

        if (
            self.allow_admins
            and not is_admin
            and user_id is not None
        ):

            try:

                from bot.middleware.auth import (
                    is_admin as auth_is_admin,
                )

                is_admin = await auth_is_admin(
                    client,
                    user_id,
                )

            except Exception:

                logger.exception(
                    "Unable to check admin status for rate limiter."
                )

        result = await self.limiter.check(
            user_id=user_id,
            chat_id=chat_id,
            action=action,
            is_admin=is_admin,
        )

        context.set(
            RATE_LIMIT_CONTEXT_KEY,
            result,
        )

        if not result.allowed:

            context.rate_limited = True

            context.set(
                RATE_LIMIT_BLOCKED_KEY,
                True,
            )

            context.set(
                RATE_LIMIT_RETRY_AFTER_KEY,
                result.retry_after,
            )

            context.block(
                "rate_limit"
            )

            await send_rate_limit_message(
                update,
                result,
            )

            logger.info(
                "Rate limit blocked request | "
                "user=%s chat=%s action=%s retry=%s",
                user_id,
                chat_id,
                action,
                result.retry_after,
            )

            return None

        context.rate_limited = False

        context.set(
            RATE_LIMIT_BLOCKED_KEY,
            False,
        )

        return await next_handler()


# ============================================================================
# Standalone check helpers
# ============================================================================

_default_limiter: Optional[
    RateLimiter
] = None


def get_default_limiter() -> RateLimiter:

    global _default_limiter

    if _default_limiter is None:

        _default_limiter = (
            RateLimiter()
        )

    return _default_limiter


async def check_rate_limit(
    client: Client,
    update: Any,
    *,
    action: Optional[str] = None,
    consume: bool = True,
) -> RateLimitResult:

    limiter = get_default_limiter()

    user_id = get_user_id(
        update
    )

    chat_id = get_chat_id(
        update
    )

    if action is None:

        action = get_action(
            update
        )

    admin = False

    if user_id is not None:

        try:

            from bot.middleware.auth import (
                is_admin,
            )

            admin = await is_admin(
                client,
                user_id,
            )

        except Exception:

            logger.debug(
                "Admin check failed during rate limiting.",
                exc_info=True,
            )

    return await limiter.check(
        user_id=user_id,
        chat_id=chat_id,
        action=action,
        is_admin=admin,
        consume=consume,
    )


async def require_rate_limit(
    client: Client,
    update: Any,
    *,
    action: Optional[str] = None,
) -> bool:

    result = await check_rate_limit(
        client,
        update,
        action=action,
    )

    if result.allowed:

        return True

    await send_rate_limit_message(
        update,
        result,
    )

    return False


# ============================================================================
# Context helpers
# ============================================================================

def get_rate_limit_result(
    context: MiddlewareContext,
) -> Optional[RateLimitResult]:

    result = context.get(
        RATE_LIMIT_CONTEXT_KEY
    )

    if isinstance(
        result,
        RateLimitResult,
    ):

        return result

    return None


def context_rate_limited(
    context: MiddlewareContext,
) -> bool:

    return bool(
        context.get(
            RATE_LIMIT_BLOCKED_KEY,
            False,
        )
    )


def context_retry_after(
    context: MiddlewareContext,
) -> float:

    try:

        return float(
            context.get(
                RATE_LIMIT_RETRY_AFTER_KEY,
                0,
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        return 0.0


# ============================================================================
# Decorator
# ============================================================================

def rate_limited(
    action: Optional[str] = None,
):
    """
    Decorator for protecting individual handlers.

    Example:

        @rate_limited("search")
        async def search_handler(client, message):
            ...
    """

    def decorator(function):

        async def wrapper(
            client: Client,
            update: Any,
            *args,
            **kwargs,
        ):

            allowed = await require_rate_limit(
                client,
                update,
                action=action,
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
            "rate_limited_handler",
        )

        wrapper.__doc__ = getattr(
            function,
            "__doc__",
            None,
        )

        return wrapper

    return decorator


# ============================================================================
# Rule presets
# ============================================================================

def create_default_limiter(
    *,
    backend: Optional[Any] = None,
) -> RateLimiter:

    return RateLimiter(
        backend=backend,
        rules=DEFAULT_RULES,
    )


def create_strict_limiter(
    *,
    backend: Optional[Any] = None,
) -> RateLimiter:

    rules = (
        RateLimitRule(
            name="global",
            limit=20,
            window=60,
            burst_limit=5,
            burst_window=5,
        ),
        RateLimitRule(
            name="search",
            limit=5,
            window=30,
            burst_limit=2,
            burst_window=5,
        ),
        RateLimitRule(
            name="download",
            limit=10,
            window=60,
            burst_limit=3,
            burst_window=5,
        ),
        RateLimitRule(
            name="verification",
            limit=5,
            window=60,
            burst_limit=2,
            burst_window=5,
        ),
    )

    return RateLimiter(
        backend=backend,
        rules=rules,
    )


# ============================================================================
# Registration
# ============================================================================

_default_middleware: Optional[
    RateLimitMiddleware
] = None


def get_default_middleware(
) -> RateLimitMiddleware:

    global _default_middleware

    if _default_middleware is None:

        _default_middleware = (
            RateLimitMiddleware(
                limiter=get_default_limiter()
            )
        )

    return _default_middleware


def register(
    app: Client,
) -> None:

    global _default_limiter
    global _default_middleware

    # Reuse an existing limiter if app.py already attached one.
    existing = getattr(
        app,
        "rate_limiter",
        None,
    )

    if isinstance(
        existing,
        RateLimiter,
    ):

        _default_limiter = existing

    else:

        _default_limiter = (
            RateLimiter()
        )

        try:

            setattr(
                app,
                "rate_limiter",
                _default_limiter,
            )

        except Exception:

            logger.debug(
                "Unable to attach rate limiter to app.",
                exc_info=True,
            )

    _default_middleware = (
        RateLimitMiddleware(
            limiter=_default_limiter
        )
    )

    logger.info(
        "Rate-limit middleware initialized."
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "RateLimitRule",
    "RateLimitResult",
    "Bucket",
    "InMemoryRateLimitBackend",
    "RedisRateLimitBackend",
    "RateLimiter",
    "RateLimitMiddleware",
    "DEFAULT_RULES",
    "check_rate_limit",
    "require_rate_limit",
    "get_rate_limit_result",
    "context_rate_limited",
    "context_retry_after",
    "rate_limited",
    "create_default_limiter",
    "create_strict_limiter",
    "get_default_limiter",
    "get_default_middleware",
    "register",
]