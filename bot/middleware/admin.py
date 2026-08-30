"""
bot.middleware.admin

Admin authorization middleware.

Responsibilities:
    - Identify Telegram administrators.
    - Support configurable admin IDs.
    - Optionally use a database/admin repository.
    - Expose admin status through context.user_data.
    - Prevent unauthorized access to admin handlers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Optional

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class AdminMiddleware:
    """
    Admin authorization middleware.

    Usage:

        middleware = AdminMiddleware(
            admin_ids={123456789}
        )

    The middleware does not perform authentication itself.
    AuthenticationMiddleware should run before this middleware.
    """

    def __init__(
        self,
        admin_ids: Optional[Iterable[int]] = None,
        *,
        admin_repository: Any = None,
        require_admin: bool = False,
    ) -> None:

        self.admin_ids: set[int] = {
            int(value)
            for value in (
                admin_ids or []
            )
        }

        self.admin_repository = (
            admin_repository
        )

        self.require_admin = (
            bool(require_admin)
        )

    # ------------------------------------------------------------------
    # Telegram ID
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_id(
        update: Update,
    ) -> Optional[int]:

        user = update.effective_user

        if user is None:
            return None

        return int(user.id)

    # ------------------------------------------------------------------
    # Static admin IDs
    # ------------------------------------------------------------------

    def is_static_admin(
        self,
        user_id: Optional[int],
    ) -> bool:

        if user_id is None:
            return False

        return int(user_id) in self.admin_ids

    # ------------------------------------------------------------------
    # Repository lookup
    # ------------------------------------------------------------------

    async def is_repository_admin(
        self,
        user_id: int,
    ) -> bool:

        repository = self.admin_repository

        if repository is None:
            return False

        for method_name in (
            "is_admin",
            "is_user_admin",
            "check_admin",
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
                    int(user_id)
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return bool(result)

            except TypeError:

                try:

                    result = method(
                        user_id=int(user_id)
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return bool(result)

                except Exception:
                    logger.exception(
                        "Admin repository lookup failed for %s",
                        user_id,
                    )
                    return False

            except Exception:

                logger.exception(
                    "Admin repository lookup failed for %s",
                    user_id,
                )

                return False

        return False

    # ------------------------------------------------------------------
    # Combined check
    # ------------------------------------------------------------------

    async def is_admin(
        self,
        user_id: Optional[int],
    ) -> bool:

        if user_id is None:
            return False

        if self.is_static_admin(user_id):
            return True

        return await self.is_repository_admin(
            int(user_id)
        )

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    @staticmethod
    def attach_admin_status(
        context: ContextTypes.DEFAULT_TYPE,
        is_admin: bool,
    ) -> None:

        context.user_data[
            "is_admin"
        ] = bool(is_admin)

    # ------------------------------------------------------------------
    # Process
    # ------------------------------------------------------------------

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:

        user_id = self.get_user_id(
            update
        )

        is_admin = await self.is_admin(
            user_id
        )

        self.attach_admin_status(
            context,
            is_admin,
        )

        if user_id is not None:

            context.user_data[
                "admin_checked"
            ] = True

        if self.require_admin and not is_admin:

            logger.warning(
                "Unauthorized admin request from %s",
                user_id,
            )

            return False

        return True

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
# Helpers
# ============================================================================

def is_admin_from_context(
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:

    return bool(
        context.user_data.get(
            "is_admin",
            False,
        )
    )


def create_admin_middleware(
    admin_ids: Optional[Iterable[int]] = None,
    *,
    admin_repository: Any = None,
    require_admin: bool = False,
) -> AdminMiddleware:

    return AdminMiddleware(
        admin_ids=admin_ids,
        admin_repository=admin_repository,
        require_admin=require_admin,
    )


__all__ = [
    "AdminMiddleware",
    "create_admin_middleware",
    "is_admin_from_context",
]