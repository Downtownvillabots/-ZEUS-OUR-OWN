"""
bot.database.verification

User verification repository.

Handles:
- Verification records
- Verification tokens
- Expiration
- Attempts
- Verified/unverified state
- Verification type
- Admin/manual verification
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, delete, func, select, update

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
)
from bot.database.models import (
    Verification,
    VerificationStatus,
    utcnow,
)

logger = logging.getLogger(__name__)


class VerificationRepository:

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
    # Token generation
    # ------------------------------------------------------------------------

    @staticmethod
    def generate_token(
        length: int = 32,
    ) -> str:

        length = max(
            16,
            min(
                int(length),
                128,
            ),
        )

        return secrets.token_urlsafe(
            length
        )[:length]

    # ------------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        verification_type: str = "default",
        expires_in_minutes: int = 30,
        token: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Verification:

        now = utcnow()

        expires_in_minutes = max(
            1,
            int(expires_in_minutes),
        )

        verification = Verification(
            user_id=int(user_id),
            verification_type=str(
                verification_type
            ),
            token=(
                token
                or self.generate_token()
            ),
            status=VerificationStatus.PENDING,
            attempts=0,
            max_attempts=5,
            expires_at=(
                now
                + timedelta(
                    minutes=expires_in_minutes
                )
            ),
            verified_at=None,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        manager = self._database(db)

        repository = getattr(
            manager,
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "create",
                None,
            )

            if method is not None:

                result = method(
                    verification
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result or verification

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            values = verification.to_dict()

            values["status"] = (
                verification.status.value
            )

            values.pop("id", None)

            object_value = orm_model(
                **values
            )

            async with manager.transaction() as session:

                session.add(object_value)
                await session.flush()

            return verification

        method = getattr(
            manager,
            "insert_verification",
            None,
        )

        if method is not None:

            result = method(
                verification
            )

            if hasattr(result, "__await__"):
                result = await result

            return result or verification

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get by token
    # ------------------------------------------------------------------------

    async def get_by_token(
        self,
        token: str,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.token
                        == str(token)
                    )
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "get_by_token",
                None,
            )

            if method is not None:

                result = method(
                    str(token)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Active verification
    # ------------------------------------------------------------------------

    async def get_active(
        self,
        user_id: int,
        *,
        verification_type: Optional[str] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            conditions = [
                orm_model.user_id == int(user_id),
                orm_model.status
                == VerificationStatus.PENDING.value,
                orm_model.expires_at > utcnow(),
            ]

            if verification_type is not None:

                conditions.append(
                    orm_model.verification_type
                    == verification_type
                )

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model)
                    .where(and_(*conditions))
                    .order_by(
                        orm_model.created_at.desc()
                    )
                    .limit(1)
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "verification",
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
                    int(user_id),
                    verification_type=verification_type,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Attempts
    # ------------------------------------------------------------------------

    async def increment_attempts(
        self,
        verification_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.id
                        == int(verification_id)
                    )
                )

                record = result.scalar_one_or_none()

                if record is None:
                    return None

                record.attempts = (
                    int(record.attempts or 0)
                    + 1
                )

                if (
                    record.attempts
                    >= int(record.max_attempts or 5)
                ):

                    record.status = (
                        VerificationStatus.EXPIRED.value
                    )

                record.updated_at = utcnow()

                await session.flush()

                return record

        repository = getattr(
            manager,
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "increment_attempts",
                None,
            )

            if method is not None:

                result = method(
                    int(verification_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------------

    async def verify(
        self,
        verification_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.id
                        == int(verification_id)
                    )
                )

                record = result.scalar_one_or_none()

                if record is None:
                    return None

                record.status = (
                    VerificationStatus.VERIFIED.value
                )

                record.verified_at = utcnow()
                record.updated_at = utcnow()

                await session.flush()

                return record

        repository = getattr(
            manager,
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "verify",
                None,
            )

            if method is not None:

                result = method(
                    int(verification_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Check token
    # ------------------------------------------------------------------------

    async def validate_token(
        self,
        token: str,
        *,
        user_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        verification = await self.get_by_token(
            token,
            db=db,
        )

        if verification is None:
            return None

        if user_id is not None:

            if int(
                verification.user_id
            ) != int(user_id):

                return None

        if verification.status != (
            VerificationStatus.PENDING
        ):

            return None

        if (
            verification.expires_at is not None
            and verification.expires_at
            <= utcnow()
        ):

            await self.expire(
                verification.id,
                db=db,
            )

            return None

        if (
            int(
                verification.attempts or 0
            )
            >= int(
                verification.max_attempts or 5
            )
        ):

            await self.expire(
                verification.id,
                db=db,
            )

            return None

        return verification

    # ------------------------------------------------------------------------
    # Expire
    # ------------------------------------------------------------------------

    async def expire(
        self,
        verification_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                await session.execute(
                    update(orm_model)
                    .where(
                        orm_model.id
                        == int(verification_id)
                    )
                    .values(
                        status=(
                            VerificationStatus.EXPIRED.value
                        ),
                        updated_at=utcnow(),
                    )
                )

            return await self.get(
                verification_id,
                db=db,
            )

        repository = getattr(
            manager,
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "expire",
                None,
            )

            if method is not None:

                result = method(
                    int(verification_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------------

    async def get(
        self,
        verification_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Verification]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.id
                        == int(verification_id)
                    )
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "verification",
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
                    int(verification_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        status: Optional[VerificationStatus] = None,
        user_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> int:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "VerificationModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if status is not None:

                conditions.append(
                    orm_model.status
                    == (
                        status.value
                        if hasattr(status, "value")
                        else status
                    )
                )

            if user_id is not None:

                conditions.append(
                    orm_model.user_id
                    == int(user_id)
                )

            statement = (
                select(func.count())
                .select_from(orm_model)
            )

            if conditions:
                statement = statement.where(
                    and_(*conditions)
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
            "verification",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "count",
                None,
            )

            if method is not None:

                result = method(
                    status=status,
                    user_id=user_id,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return int(result or 0)

        raise RuntimeError(
            "No verification persistence adapter is configured."
        )

    async def statistics(
        self,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> dict[str, int]:

        return {
            "total": await self.count(db=db),
            "pending": await self.count(
                status=VerificationStatus.PENDING,
                db=db,
            ),
            "verified": await self.count(
                status=VerificationStatus.VERIFIED,
                db=db,
            ),
            "expired": await self.count(
                status=VerificationStatus.EXPIRED,
                db=db,
            ),
        }


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[
    VerificationRepository
] = None


def get_repository(
    db: Optional[DatabaseManager] = None,
) -> VerificationRepository:

    global _default_repository

    if db is not None:
        return VerificationRepository(db)

    if _default_repository is None:
        _default_repository = VerificationRepository()

    return _default_repository


async def create_verification(**kwargs):

    db = kwargs.pop("db", None)

    return await get_repository(db).create(
        **kwargs
    )


async def validate_token(
    token: str,
    *,
    user_id: Optional[int] = None,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).validate_token(
        token,
        user_id=user_id,
    )


async def verify(
    verification_id: int,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).verify(
        verification_id
    )


__all__ = [
    "VerificationRepository",
    "get_repository",
    "create_verification",
    "validate_token",
    "verify",
]