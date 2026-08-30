"""
bot.database.premium

Premium/subscription repository.

Handles:
- Premium activation
- Premium expiration
- Subscription plans
- Payment references
- Renewal
- Cancellation
- User premium status
- Expiration cleanup
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, delete, func, select, update

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
)
from bot.database.models import (
    PremiumSubscription,
    PremiumStatus,
    utcnow,
)

logger = logging.getLogger(__name__)


class PremiumRepository:

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
    ) -> None:

        self.db = db or get_database_manager()

    def _database(
        self,
        db: Optional[DatabaseManager] = None,
    ) -> DatabaseManager:

        manager = (
            db
            or self.db
            or get_database_manager()
        )

        if manager is None:
            raise RuntimeError(
                "Database is not initialized."
            )

        return manager

    # ------------------------------------------------------------------------
    # Create subscription
    # ------------------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        plan: str,
        duration_days: int,
        price: Optional[float] = None,
        currency: Optional[str] = None,
        payment_id: Optional[str] = None,
        provider: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        db: Optional[DatabaseManager] = None,
    ) -> PremiumSubscription:

        now = utcnow()

        duration_days = max(
            1,
            int(duration_days),
        )

        expires_at = (
            now
            + timedelta(
                days=duration_days
            )
        )

        subscription = PremiumSubscription(
            user_id=int(user_id),
            plan=str(plan),
            status=PremiumStatus.ACTIVE,
            price=price,
            currency=currency,
            payment_id=payment_id,
            provider=provider,
            started_at=now,
            expires_at=expires_at,
            cancelled_at=None,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        manager = self._database(db)

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "create",
                None,
            )

            if method is not None:

                result = method(subscription)

                if hasattr(result, "__await__"):
                    result = await result

                return result or subscription

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            values = subscription.to_dict()

            values["status"] = (
                subscription.status.value
            )

            values.pop("id", None)

            object_value = orm_model(
                **values
            )

            async with manager.transaction() as session:

                session.add(object_value)
                await session.flush()

            return subscription

        method = getattr(
            manager,
            "insert_premium_subscription",
            None,
        )

        if method is not None:

            result = method(subscription)

            if hasattr(result, "__await__"):
                result = await result

            return result or subscription

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Active subscription
    # ------------------------------------------------------------------------

    async def get_active(
        self,
        user_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[PremiumSubscription]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            now = utcnow()

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model)
                    .where(
                        and_(
                            orm_model.user_id
                            == int(user_id),
                            orm_model.status
                            == PremiumStatus.ACTIVE.value,
                            orm_model.expires_at
                            > now,
                        )
                    )
                    .order_by(
                        orm_model.expires_at.desc()
                    )
                    .limit(1)
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "get_active",
                None,
            )

            if method is not None:

                result = method(
                    int(user_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        method = getattr(
            manager,
            "get_active_premium",
            None,
        )

        if method is not None:

            result = method(
                int(user_id)
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Check premium
    # ------------------------------------------------------------------------

    async def is_active(
        self,
        user_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> bool:

        subscription = await self.get_active(
            user_id,
            db=db,
        )

        return subscription is not None

    # ------------------------------------------------------------------------
    # Extend
    # ------------------------------------------------------------------------

    async def extend(
        self,
        user_id: int,
        days: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[PremiumSubscription]:

        days = max(
            1,
            int(days),
        )

        subscription = await self.get_active(
            user_id,
            db=db,
        )

        if subscription is None:

            return await self.create(
                user_id=user_id,
                plan="manual",
                duration_days=days,
                db=db,
            )

        current_expiry = (
            subscription.expires_at
            or utcnow()
        )

        if current_expiry < utcnow():
            current_expiry = utcnow()

        new_expiry = (
            current_expiry
            + timedelta(days=days)
        )

        return await self.update(
            subscription.id,
            {
                "expires_at": new_expiry,
                "status": PremiumStatus.ACTIVE,
            },
            db=db,
        )

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    async def update(
        self,
        subscription_id: int,
        fields: dict[str, Any],
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[PremiumSubscription]:

        allowed = {
            "plan",
            "status",
            "price",
            "currency",
            "payment_id",
            "provider",
            "started_at",
            "expires_at",
            "cancelled_at",
            "metadata",
        }

        invalid = set(fields) - allowed

        if invalid:
            raise ValueError(
                "Unsupported premium fields: "
                + ", ".join(sorted(invalid))
            )

        values = dict(fields)
        values["updated_at"] = utcnow()

        if "status" in values:
            value = values["status"]

            if hasattr(value, "value"):
                values["status"] = value.value

        manager = self._database(db)

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "update",
                None,
            )

            if method is not None:

                result = method(
                    int(subscription_id),
                    values,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                await session.execute(
                    update(orm_model)
                    .where(
                        orm_model.id
                        == int(subscription_id)
                    )
                    .values(**values)
                )

            return await self.get(
                subscription_id,
                db=db,
            )

        method = getattr(
            manager,
            "update_premium_subscription",
            None,
        )

        if method is not None:

            result = method(
                int(subscription_id),
                values,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------------

    async def get(
        self,
        subscription_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[PremiumSubscription]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.id
                        == int(subscription_id)
                    )
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "get",
                None,
            )

            if method is not None:

                result = method(
                    int(subscription_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------------

    async def cancel(
        self,
        subscription_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[PremiumSubscription]:

        return await self.update(
            subscription_id,
            {
                "status": PremiumStatus.CANCELLED,
                "cancelled_at": utcnow(),
            },
            db=db,
        )

    # ------------------------------------------------------------------------
    # Expiration
    # ------------------------------------------------------------------------

    async def expire_subscriptions(
        self,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> int:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            now = utcnow()

            async with manager.transaction() as session:

                result = await session.execute(
                    update(orm_model)
                    .where(
                        and_(
                            orm_model.status
                            == PremiumStatus.ACTIVE.value,
                            orm_model.expires_at
                            <= now,
                        )
                    )
                    .values(
                        status=PremiumStatus.EXPIRED.value,
                        updated_at=now,
                    )
                )

                return int(
                    result.rowcount or 0
                )

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "expire_subscriptions",
                None,
            )

            if method is not None:

                result = method()

                if hasattr(result, "__await__"):
                    result = await result

                return int(result or 0)

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        status: Optional[PremiumStatus] = None,
        db: Optional[DatabaseManager] = None,
    ) -> int:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "PremiumSubscriptionModel",
            None,
        )

        if orm_model is not None:

            statement = (
                select(func.count())
                .select_from(orm_model)
            )

            if status is not None:

                value = (
                    status.value
                    if hasattr(status, "value")
                    else status
                )

                statement = statement.where(
                    orm_model.status == value
                )

            async with manager.session_context() as session:

                result = await session.execute(
                    statement
                )

                return int(
                    result.scalar() or 0
                )

        repository = getattr(
            manager,
            "premium",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "count",
                None,
            )

            if method is not None:

                result = method(status=status)

                if hasattr(result, "__await__"):
                    result = await result

                return int(result or 0)

        raise RuntimeError(
            "No premium persistence adapter is configured."
        )

    async def statistics(
        self,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> dict[str, int]:

        return {
            "total": await self.count(db=db),
            "active": await self.count(
                status=PremiumStatus.ACTIVE,
                db=db,
            ),
            "expired": await self.count(
                status=PremiumStatus.EXPIRED,
                db=db,
            ),
            "cancelled": await self.count(
                status=PremiumStatus.CANCELLED,
                db=db,
            ),
        }


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[PremiumRepository] = None


def get_repository(
    db: Optional[DatabaseManager] = None,
) -> PremiumRepository:

    global _default_repository

    if db is not None:
        return PremiumRepository(db)

    if _default_repository is None:
        _default_repository = PremiumRepository()

    return _default_repository


async def create_subscription(**kwargs):

    db = kwargs.pop("db", None)

    return await get_repository(db).create(
        **kwargs
    )


async def is_premium(
    user_id: int,
    *,
    db: Optional[DatabaseManager] = None,
) -> bool:

    return await get_repository(db).is_active(
        user_id
    )


async def extend_premium(
    user_id: int,
    days: int,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).extend(
        user_id,
        days,
    )


async def cancel_subscription(
    subscription_id: int,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).cancel(
        subscription_id
    )


__all__ = [
    "PremiumRepository",
    "get_repository",
    "create_subscription",
    "is_premium",
    "extend_premium",
    "cancel_subscription",
]