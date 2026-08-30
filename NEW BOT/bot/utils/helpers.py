"""
General-purpose helpers.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, Optional, TypeVar


logger = logging.getLogger(
    "bot.utils"
)


T = TypeVar("T")


async def maybe_await(
    value: T | Awaitable[T],
) -> T:

    if inspect.isawaitable(value):
        return await value

    return value


async def retry_async(
    function: Callable[..., Awaitable[T]],
    *args: Any,
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[
        type[Exception],
        ...,
    ] = (Exception,),
    **kwargs: Any,
) -> T:

    attempts = max(
        1,
        int(attempts),
    )

    current_delay = max(
        0.0,
        float(delay),
    )

    last_error: Optional[
        Exception
    ] = None

    for attempt in range(
        attempts
    ):

        try:

            return await function(
                *args,
                **kwargs,
            )

        except exceptions as error:

            last_error = error

            if attempt >= attempts - 1:
                raise

            if current_delay > 0:

                await asyncio.sleep(
                    current_delay
                )

            current_delay *= max(
                1.0,
                float(backoff),
            )

    if last_error is not None:
        raise last_error

    raise RuntimeError(
        "Retry operation failed."
    )


def clamp(
    value: float | int,
    minimum: float | int,
    maximum: float | int,
) -> float | int:

    if minimum > maximum:
        raise ValueError(
            "minimum cannot exceed maximum."
        )

    return max(
        minimum,
        min(
            value,
            maximum,
        ),
    )


def chunked(
    values: list[T],
    size: int,
) -> list[list[T]]:

    size = max(
        1,
        int(size),
    )

    return [
        values[index:index + size]
        for index in range(
            0,
            len(values),
            size,
        )
    ]


def unique(
    values: list[T],
) -> list[T]:

    result = []
    seen = set()

    for value in values:

        try:
            marker = value

            if marker in seen:
                continue

            seen.add(marker)
            result.append(value)

        except TypeError:

            marker = repr(value)

            if marker in seen:
                continue

            seen.add(marker)
            result.append(value)

    return result


def random_choice(
    values: list[T],
    default: Optional[T] = None,
) -> Optional[T]:

    if not values:
        return default

    return random.choice(
        values
    )


def mask_string(
    value: Optional[str],
    *,
    visible: int = 4,
    mask: str = "*",
) -> str:

    if not value:
        return ""

    text = str(value)

    visible = max(
        0,
        int(visible),
    )

    if len(text) <= visible:
        return mask * len(text)

    return (
        text[:visible]
        + mask * (
            len(text) - visible
        )
    )


def safe_int(
    value: Any,
    default: int = 0,
) -> int:

    try:
        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def safe_float(
    value: Any,
    default: float = 0.0,
) -> float:

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def debounce(
    seconds: float,
):
    """
    Async debounce decorator.

    A later call cancels the pending execution for the same
    decorated function.
    """

    delay = max(
        0.0,
        float(seconds),
    )

    tasks: dict[
        str,
        asyncio.Task,
    ] = {}

    def decorator(function):

        @wraps(function)
        async def wrapper(
            *args,
            **kwargs,
        ):

            key = repr(
                (
                    args,
                    sorted(
                        kwargs.items()
                    ),
                )
            )

            existing = tasks.get(
                key
            )

            if existing is not None:
                existing.cancel()

            async def runner():

                await asyncio.sleep(
                    delay
                )

                return await function(
                    *args,
                    **kwargs,
                )

            task = asyncio.create_task(
                runner()
            )

            tasks[key] = task

            try:

                return await task

            finally:

                if tasks.get(
                    key
                ) is task:

                    tasks.pop(
                        key,
                        None,
                    )

        return wrapper

    return decorator


__all__ = [
    "maybe_await",
    "retry_async",
    "clamp",
    "chunked",
    "unique",
    "random_choice",
    "mask_string",
    "safe_int",
    "safe_float",
    "debounce",
]