"""
Authentication middleware.

Responsibilities:
    - Ensure Telegram users are known to the application.
    - Create/register users when required.
    - Attach the application user to handler context.
    - Block banned/deactivated users.
    - Keep authentication logic out of handlers.

Designed for python-telegram-bot.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from telegram import Update
from telegram.ext import BaseHandler, ContextTypes

logger = logging.getLogger(__name__)


class AuthenticationMiddleware:
    """
    Authentication/registration middleware.

    The middleware is intentionally tolerant of different user repository
    implementations because the database layer may expose helpers rather
    than one fixed repository API.
    """

    def __init__(
        self,
        user_repository: Any = None,
        *,
        allow_anonymous: bool = False,
    ) -> None:

        self.user_repository = user_repository
        self.allow_anonymous = allow_anonymous

    # ------------------------------------------------------------------
    # Telegram user extraction
    # ------------------------------------------------------------------

    @staticmethod
    def get_telegram_user(
        update: Update,
    ) -> Any:

        if update.effective_user is not None:
            return update.effective_user

        return None

    # ------------------------------------------------------------------
    # Repository lookup
    # ------------------------------------------------------------------

    async def _get_user(
        self,
        telegram_id: int,
    ) -> Any:

        repository = self.user_repository

        if repository is None:
            return None

        methods = (
            "get_by_telegram_id",
            "get_by_id",
            "get",
        )

        for method_name in methods:

            method = getattr(
                repository,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                result = method(
                    int(telegram_id)
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return result

            except TypeError:

                try:

                    result = method(
                        telegram_id=int(
                            telegram_id
                        )
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return result

                except Exception:
                    logger.exception(
                        "Failed to lookup user %s",
                        telegram_id,
                    )
                    return None

            except Exception:

                logger.exception(
                    "Failed to lookup user %s",
                    telegram_id,
                )

                return None

        return None

    # ------------------------------------------------------------------
    # Repository creation
    # ------------------------------------------------------------------

    async def _create_user(
        self,
        telegram_user: Any,
    ) -> Any:

        repository = self.user_repository

        if repository is None:
            return None

        payload = {
            "telegram_id": int(
                telegram_user.id
            ),
            "username": getattr(
                telegram_user,
                "username",
                None,
            ),
            "first_name": getattr(
                telegram_user,
                "first_name",
                None,
            ),
            "last_name": getattr(
                telegram_user,
                "last_name",
                None,
            ),
            "language_code": getattr(
                telegram_user,
                "language_code",
                None,
            ),
        }

        for method_name in (
            "create",
            "create_user",
            "register",
            "get_or_create",
        ):

            method = getattr(
                repository,
                method_name,
                None,
            )

            if method is None:
                continue

            try:

                result = method(
                    **payload
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return result

            except TypeError:

                try:

                    result = method(
                        int(
                            telegram_user.id
                        )
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return result

                except Exception:
                    logger.exception(
                        "Failed creating user %s",
                        telegram_user.id,
                    )
                    return None

            except Exception:

                logger.exception(
                    "Failed creating user %s",
                    telegram_user.id,
                )

                return None

        return None

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_banned(
        user: Any,
    ) -> bool:

        if user is None:
            return False

        for attribute in (
            "is_banned",
            "banned",
            "blocked",
        ):

            value = getattr(
                user,
                attribute,
                None,
            )

            if value is not None:
                return bool(value)

        status = getattr(
            user,
            "status",
            None,
        )

        if status is not None:

            return str(
                getattr(
                    status,
                    "value",
                    status,
                )
            ).lower() in {
                "banned",
                "blocked",
                "disabled",
            }

        return False

    @staticmethod
    def _is_active(
        user: Any,
    ) -> bool:

        if user is None:
            return True

        value = getattr(
            user,
            "is_active",
            None,
        )

        if value is not None:
            return bool(value)

        value = getattr(
            user,
            "active",
            None,
        )

        if value is not None:
            return bool(value)

        return True

    # ------------------------------------------------------------------
    # Context attachment
    # ------------------------------------------------------------------

    @staticmethod
    def attach_user(
        context: ContextTypes.DEFAULT_TYPE,
        user: Any,
    ) -> None:

        context.user_data["db_user"] = user
        context.user_data["authenticated"] = (
            user is not None
        )

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        telegram_user = self.get_telegram_user(
            update
        )

        if telegram_user is None:

            if self.allow_anonymous:
                return True

            return False

        telegram_id = int(
            telegram_user.id
        )

        user = await self._get_user(
            telegram_id
        )

        if user is None:

            user = await self._create_user(
                telegram_user
            )

        if user is None:

            logger.warning(
                "Unable to authenticate Telegram user %s",
                telegram_id,
            )

            if self.allow_anonymous:
                return True

            return False

        if self._is_banned(user):

            context.user_data[
                "authenticated"
            ] = False

            context.user_data[
                "blocked"
            ] = True

            logger.info(
                "Blocked banned user %s",
                telegram_id,
            )

            return False

        if not self._is_active(user):

            context.user_data[
                "authenticated"
            ] = False

            context.user_data[
                "blocked"
            ] = True

            return False

        self.attach_user(
            context,
            user,
        )

        context.user_data[
            "telegram_user_id"
        ] = telegram_id

        return True

    # ------------------------------------------------------------------
    # PTB handler callback
    # ------------------------------------------------------------------

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
# Convenience factory
# ============================================================================

def create_auth_middleware(
    user_repository: Any = None,
    *,
    allow_anonymous: bool = False,
) -> AuthenticationMiddleware:

    return AuthenticationMiddleware(
        user_repository=user_repository,
        allow_anonymous=allow_anonymous,
    )


__all__ = [
    "AuthenticationMiddleware",
    "create_auth_middleware",
]