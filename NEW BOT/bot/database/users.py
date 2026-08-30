"""
bot.database.users

User repository.

Responsibilities
----------------
- Create/update Telegram users
- Lookup users
- Update profile information
- Ban/unban users
- Manage roles/admin state
- Manage premium/verification flags
- Track last seen
- Pagination
- User statistics
- Safe repository-level database access

The repository does not contain Telegram handler logic.

Expected database model:
    bot.database.models.User

The implementation uses SQLAlchemy Core/ORM-compatible patterns while
keeping the repository usable with the DatabaseManager from connection.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.exc import SQLAlchemyError

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
    session,
    transaction,
)
from bot.database.models import (
    User,
    UserRole,
    UserStatus,
    utcnow,
    validate_user_id,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Compatibility helpers
# ============================================================================

def _enum_value(value: Any) -> Any:
    """
    Convert Enum values into database-friendly values.
    """

    if isinstance(
        value,
        (
            UserRole,
            UserStatus,
        ),
    ):

        return value.value

    return value


def _model_class(
    db: Any = None,
):
    """
    Resolve the SQLAlchemy User model if the project later exposes one.

    The dataclass from models.py is still the canonical domain model.
    """

    if db is not None:

        value = getattr(
            db,
            "User",
            None,
        )

        if value is not None:

            return value

    return User


def _row_to_user(
    row: Any,
) -> Optional[User]:

    if row is None:
        return None

    if isinstance(
        row,
        User,
    ):

        return row

    # SQLAlchemy ORM object.
    if hasattr(
        row,
        "__table__",
    ):

        values = {}

        for column in row.__table__.columns:

            name = column.name

            try:

                values[name] = getattr(
                    row,
                    name,
                )

            except AttributeError:

                continue

        return _coerce_user(
            values
        )

    # SQLAlchemy Row.
    if hasattr(
        row,
        "_mapping",
    ):

        mapping = dict(
            row._mapping
        )

        # Handle an ORM object returned as the only mapped value.
        if len(mapping) == 1:

            value = next(
                iter(
                    mapping.values()
                )
            )

            if value is not row:

                return _row_to_user(
                    value
                )

        return _coerce_user(
            mapping
        )

    if isinstance(
        row,
        dict,
    ):

        return _coerce_user(
            row
        )

    return None


def _coerce_user(
    data: dict[str, Any],
) -> User:

    allowed = {
        "id",
        "username",
        "first_name",
        "last_name",
        "language_code",
        "is_bot",
        "status",
        "role",
        "is_admin",
        "is_premium",
        "is_verified",
        "premium_until",
        "verification_until",
        "ban_reason",
        "last_seen_at",
        "created_at",
        "updated_at",
        "metadata",
    }

    values = {
        key: value
        for key, value in data.items()
        if key in allowed
    }

    if "id" not in values:

        raise ValueError(
            "User database row does not contain id."
        )

    status = values.get(
        "status"
    )

    if (
        status is not None
        and not isinstance(
            status,
            UserStatus,
        )
    ):

        try:

            values["status"] = UserStatus(
                status
            )

        except ValueError:

            values["status"] = (
                UserStatus.ACTIVE
            )

    role = values.get(
        "role"
    )

    if (
        role is not None
        and not isinstance(
            role,
            UserRole,
        )
    ):

        try:

            values["role"] = UserRole(
                role
            )

        except ValueError:

            values["role"] = (
                UserRole.USER
            )

    return User(
        **values
    )


# ============================================================================
# Repository
# ============================================================================

class UserRepository:
    """
    Repository for User persistence.

    Usage:

        repo = UserRepository()

        user = await repo.get(123456789)

        user = await repo.upsert(
            user_id=123456789,
            username="example",
        )
    """

    def __init__(
        self,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> None:

        self.db = (
            db
            or get_database_manager()
        )

    # ------------------------------------------------------------------------
    # Database manager
    # ------------------------------------------------------------------------

    def _database(
        self,
        db: Optional[
            DatabaseManager
        ] = None,
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
    # Create / upsert
    # ------------------------------------------------------------------------

    async def create(
        self,
        user_id: int,
        *,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
        is_bot: bool = False,
        status: UserStatus = UserStatus.ACTIVE,
        role: UserRole = UserRole.USER,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> User:

        user_id = validate_user_id(
            user_id
        )

        now = utcnow()

        user = User(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            is_bot=bool(
                is_bot
            ),
            status=status,
            role=role,
            is_admin=(
                role
                in {
                    UserRole.ADMIN,
                    UserRole.OWNER,
                }
            ),
            created_at=now,
            updated_at=now,
            metadata=(
                metadata
                or {}
            ),
        )

        manager = self._database(
            db
        )

        # If a repository-specific ORM implementation is supplied by
        # connection.py, use it.
        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            creator = getattr(
                repository,
                "create",
                None,
            )

            if creator is not None:

                result = creator(
                    user
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_user(
                        result
                    )
                    or user
                )

        # Generic ORM hook.
        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            values = user.to_dict()

            try:

                values["status"] = (
                    _enum_value(
                        values["status"]
                    )
                )

                values["role"] = (
                    _enum_value(
                        values["role"]
                    )
                )

                object_value = orm_model(
                    **values
                )

                async with manager.transaction() as db_session:

                    db_session.add(
                        object_value
                    )

                    await db_session.flush()

                return (
                    _row_to_user(
                        object_value
                    )
                    or user
                )

            except Exception:

                logger.exception(
                    "Unable to create user through ORM."
                )

                raise

        # Fall back to a repository-level raw insert if provided.
        insert_method = getattr(
            manager,
            "insert_user",
            None,
        )

        if insert_method is not None:

            result = insert_method(
                user
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_user(
                    result
                )
                or user
            )

        raise RuntimeError(
            "No user persistence adapter is configured. "
            "Implement UserModel or DatabaseManager.insert_user()."
        )

    async def upsert(
        self,
        user_id: int,
        *,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
        is_bot: bool = False,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        preserve_admin: bool = True,
        preserve_role: bool = True,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> User:

        user_id = validate_user_id(
            user_id
        )

        existing = await self.get(
            user_id,
            db=db,
        )

        if existing is None:

            return await self.create(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                is_bot=is_bot,
                metadata=metadata,
                db=db,
            )

        existing.username = username

        existing.first_name = first_name

        existing.last_name = last_name

        existing.language_code = (
            language_code
        )

        existing.is_bot = bool(
            is_bot
        )

        if metadata:

            existing.metadata.update(
                metadata
            )

        existing.updated_at = utcnow()

        # Do not accidentally revoke privileged state during normal
        # Telegram profile synchronization.
        if not preserve_admin:

            existing.is_admin = False

        if not preserve_role:

            existing.role = UserRole.USER

        await self.update(
            existing,
            db=db,
        )

        return existing

    # ------------------------------------------------------------------------
    # Telegram convenience method
    # ------------------------------------------------------------------------

    async def upsert_telegram_user(
        self,
        telegram_user: Any,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> User:

        if telegram_user is None:

            raise ValueError(
                "telegram_user is required."
            )

        user_id = getattr(
            telegram_user,
            "id",
            None,
        )

        if user_id is None:

            raise ValueError(
                "Telegram user does not contain id."
            )

        return await self.upsert(
            int(
                user_id
            ),
            username=getattr(
                telegram_user,
                "username",
                None,
            ),
            first_name=getattr(
                telegram_user,
                "first_name",
                None,
            ),
            last_name=getattr(
                telegram_user,
                "last_name",
                None,
            ),
            language_code=getattr(
                telegram_user,
                "language_code",
                None,
            ),
            is_bot=bool(
                getattr(
                    telegram_user,
                    "is_bot",
                    False,
                )
            ),
            db=db,
        )

    # ------------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------------

    async def get(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        user_id = validate_user_id(
            user_id
        )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            getter = getattr(
                repository,
                "get",
                None,
            )

            if getter is not None:

                result = getter(
                    user_id
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_user(
                    result
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.id
                        == user_id
                    )
                )

                return _row_to_user(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_user",
            None,
        )

        if getter is not None:

            result = getter(
                user_id
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_user(
                result
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    async def exists(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        return (
            await self.get(
                user_id,
                db=db,
            )
            is not None
        )

    async def get_by_username(
        self,
        username: str,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        username = (
            str(username)
            .strip()
            .lstrip("@")
        )

        if not username:

            return None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            getter = getattr(
                repository,
                "get_by_username",
                None,
            )

            if getter is not None:

                result = getter(
                    username
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_user(
                    result
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        func.lower(
                            orm_model.username
                        )
                        == username.lower()
                    )
                )

                return _row_to_user(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_user_by_username",
            None,
        )

        if getter is not None:

            result = getter(
                username
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_user(
                result
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    async def update(
        self,
        user: User,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> User:

        user_id = validate_user_id(
            user.id
        )

        user.updated_at = utcnow()

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            updater = getattr(
                repository,
                "update",
                None,
            )

            if updater is not None:

                result = updater(
                    user
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_user(
                        result
                    )
                    or user
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            values = user.to_dict()

            values["status"] = (
                _enum_value(
                    values["status"]
                )
            )

            values["role"] = (
                _enum_value(
                    values["role"]
                )
            )

            values.pop(
                "id",
                None,
            )

            async with manager.transaction() as db_session:

                await db_session.execute(
                    update(
                        orm_model
                    )
                    .where(
                        orm_model.id
                        == user_id
                    )
                    .values(
                        **values
                    )
                )

            return user

        updater = getattr(
            manager,
            "update_user",
            None,
        )

        if updater is not None:

            result = updater(
                user
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_user(
                    result
                )
                or user
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    async def update_fields(
        self,
        user_id: int,
        fields: dict[str, Any],
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        user_id = validate_user_id(
            user_id
        )

        if not fields:
            return await self.get(
                user_id,
                db=db,
            )

        allowed = {
            "username",
            "first_name",
            "last_name",
            "language_code",
            "is_bot",
            "status",
            "role",
            "is_admin",
            "is_premium",
            "is_verified",
            "premium_until",
            "verification_until",
            "ban_reason",
            "last_seen_at",
            "metadata",
        }

        invalid = (
            set(fields)
            - allowed
        )

        if invalid:

            raise ValueError(
                "Unsupported user fields: "
                + ", ".join(
                    sorted(
                        invalid
                    )
                )
            )

        values = dict(
            fields
        )

        values[
            "updated_at"
        ] = utcnow()

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            updater = getattr(
                repository,
                "update_fields",
                None,
            )

            if updater is not None:

                result = updater(
                    user_id,
                    values,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_user(
                    result
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            for key, value in list(
                values.items()
            ):

                values[key] = _enum_value(
                    value
                )

            async with manager.transaction() as db_session:

                await db_session.execute(
                    update(
                        orm_model
                    )
                    .where(
                        orm_model.id
                        == user_id
                    )
                    .values(
                        **values
                    )
                )

            return await self.get(
                user_id,
                db=db,
            )

        updater = getattr(
            manager,
            "update_user_fields",
            None,
        )

        if updater is not None:

            result = updater(
                user_id,
                values,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_user(
                result
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Last seen
    # ------------------------------------------------------------------------

    async def mark_seen(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        now = utcnow()

        return await self.update_fields(
            user_id,
            {
                "last_seen_at": now,
            },
            db=db,
        )

    # ------------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------------

    async def set_status(
        self,
        user_id: int,
        status: UserStatus,
        *,
        ban_reason: Optional[str] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        values = {
            "status": status,
        }

        if status in {
            UserStatus.BANNED,
            UserStatus.BLOCKED,
        }:

            values[
                "ban_reason"
            ] = ban_reason

        else:

            values[
                "ban_reason"
            ] = None

        return await self.update_fields(
            user_id,
            values,
            db=db,
        )

    async def ban(
        self,
        user_id: int,
        reason: Optional[str] = None,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_status(
            user_id,
            UserStatus.BANNED,
            ban_reason=reason,
            db=db,
        )

    async def unban(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_status(
            user_id,
            UserStatus.ACTIVE,
            db=db,
        )

    async def disable(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_status(
            user_id,
            UserStatus.DISABLED,
            db=db,
        )

    async def activate(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_status(
            user_id,
            UserStatus.ACTIVE,
            db=db,
        )

    async def is_banned(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        user = await self.get(
            user_id,
            db=db,
        )

        if user is None:
            return False

        return user.is_banned

    # ------------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------------

    async def set_role(
        self,
        user_id: int,
        role: UserRole,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        is_admin = role in {
            UserRole.ADMIN,
            UserRole.OWNER,
        }

        return await self.update_fields(
            user_id,
            {
                "role": role,
                "is_admin": is_admin,
            },
            db=db,
        )

    async def make_admin(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_role(
            user_id,
            UserRole.ADMIN,
            db=db,
        )

    async def remove_admin(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.set_role(
            user_id,
            UserRole.USER,
            db=db,
        )

    async def set_admin(
        self,
        user_id: int,
        value: bool,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.update_fields(
            user_id,
            {
                "is_admin": bool(
                    value
                ),
                "role": (
                    UserRole.ADMIN
                    if value
                    else UserRole.USER
                ),
            },
            db=db,
        )

    async def is_admin(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        user = await self.get(
            user_id,
            db=db,
        )

        if user is None:
            return False

        return bool(
            user.is_admin
            or user.role
            in {
                UserRole.ADMIN,
                UserRole.OWNER,
            }
        )

    # ------------------------------------------------------------------------
    # Premium
    # ------------------------------------------------------------------------

    async def set_premium(
        self,
        user_id: int,
        active: bool,
        *,
        premium_until: Optional[
            datetime
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.update_fields(
            user_id,
            {
                "is_premium": bool(
                    active
                ),
                "premium_until": (
                    premium_until
                    if active
                    else None
                ),
            },
            db=db,
        )

    async def is_premium(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        user = await self.get(
            user_id,
            db=db,
        )

        if user is None:
            return False

        if not user.is_premium:
            return False

        if (
            user.premium_until is not None
            and utcnow()
            >= user.premium_until
        ):

            # Keep the persisted state consistent.
            try:

                await self.set_premium(
                    user_id,
                    False,
                    db=db,
                )

            except Exception:

                logger.exception(
                    "Unable to expire premium flag for user %s.",
                    user_id,
                )

            return False

        return True

    # ------------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------------

    async def set_verified(
        self,
        user_id: int,
        verified: bool,
        *,
        verification_until: Optional[
            datetime
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[User]:

        return await self.update_fields(
            user_id,
            {
                "is_verified": bool(
                    verified
                ),
                "verification_until": (
                    verification_until
                    if verified
                    else None
                ),
            },
            db=db,
        )

    async def is_verified(
        self,
        user_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        user = await self.get(
            user_id,
            db=db,
        )

        if user is None:
            return False

        if not user.is_verified:
            return False

        if (
            user.verification_until is not None
            and utcnow()
            >= user.verification_until
        ):

            try:

                await self.set_verified(
                    user_id,
                    False,
                    db=db,
                )

            except Exception:

                logger.exception(
                    "Unable to expire verification flag for user %s.",
                    user_id,
                )

            return False

        return True

    # ------------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[User]:

        query = (
            str(query)
            .strip()
        )

        if not query:
            return []

        limit = max(
            1,
            min(
                int(limit),
                100,
            ),
        )

        offset = max(
            0,
            int(offset),
        )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            search_method = getattr(
                repository,
                "search",
                None,
            )

            if search_method is not None:

                result = search_method(
                    query,
                    limit=limit,
                    offset=offset,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    user
                    for user in (
                        _row_to_user(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if user is not None
                ]

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            pattern = (
                f"%{query}%"
            )

            conditions = [
                orm_model.username.ilike(
                    pattern
                ),
                orm_model.first_name.ilike(
                    pattern
                ),
                orm_model.last_name.ilike(
                    pattern
                ),
            ]

            try:

                numeric_id = int(
                    query
                )

                conditions.append(
                    orm_model.id
                    == numeric_id
                )

            except ValueError:

                pass

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    )
                    .where(
                        or_(
                            *conditions
                        )
                    )
                    .order_by(
                        orm_model.id.desc()
                    )
                    .offset(
                        offset
                    )
                    .limit(
                        limit
                    )
                )

                return [
                    _row_to_user(
                        row
                    )
                    for row in (
                        result.scalars().all()
                    )
                    if _row_to_user(
                        row
                    ) is not None
                ]

        search_method = getattr(
            manager,
            "search_users",
            None,
        )

        if search_method is not None:

            result = search_method(
                query,
                limit=limit,
                offset=offset,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return [
                user
                for user in (
                    _row_to_user(
                        row
                    )
                    for row in (
                        result
                        or []
                    )
                )
                if user is not None
            ]

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------------

    async def list_users(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[
            UserStatus
        ] = None,
        role: Optional[
            UserRole
        ] = None,
        premium_only: bool = False,
        verified_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[User]:

        limit = max(
            1,
            min(
                int(limit),
                100,
            ),
        )

        offset = max(
            0,
            int(offset),
        )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            list_method = getattr(
                repository,
                "list_users",
                None,
            )

            if list_method is not None:

                result = list_method(
                    limit=limit,
                    offset=offset,
                    status=status,
                    role=role,
                    premium_only=premium_only,
                    verified_only=verified_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    user
                    for user in (
                        _row_to_user(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if user is not None
                ]

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if status is not None:

                conditions.append(
                    orm_model.status
                    == _enum_value(
                        status
                    )
                )

            if role is not None:

                conditions.append(
                    orm_model.role
                    == _enum_value(
                        role
                    )
                )

            if premium_only:

                conditions.append(
                    orm_model.is_premium
                    == True
                )

            if verified_only:

                conditions.append(
                    orm_model.is_verified
                    == True
                )

            statement = select(
                orm_model
            )

            if conditions:

                statement = statement.where(
                    and_(
                        *conditions
                    )
                )

            statement = (
                statement
                .order_by(
                    orm_model.id.desc()
                )
                .offset(
                    offset
                )
                .limit(
                    limit
                )
            )

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    statement
                )

                rows = result.scalars().all()

                users = []

                for row in rows:

                    user = _row_to_user(
                        row
                    )

                    if user is not None:

                        users.append(
                            user
                        )

                return users

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Counts / statistics
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        status: Optional[
            UserStatus
        ] = None,
        premium_only: bool = False,
        verified_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> int:

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            count_method = getattr(
                repository,
                "count",
                None,
            )

            if count_method is not None:

                result = count_method(
                    status=status,
                    premium_only=premium_only,
                    verified_only=verified_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return int(
                    result or 0
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if status is not None:

                conditions.append(
                    orm_model.status
                    == _enum_value(
                        status
                    )
                )

            if premium_only:

                conditions.append(
                    orm_model.is_premium
                    == True
                )

            if verified_only:

                conditions.append(
                    orm_model.is_verified
                    == True
                )

            statement = select(
                func.count()
            ).select_from(
                orm_model
            )

            if conditions:

                statement = statement.where(
                    and_(
                        *conditions
                    )
                )

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    statement
                )

                return int(
                    result.scalar()
                    or 0
                )

        count_method = getattr(
            manager,
            "count_users",
            None,
        )

        if count_method is not None:

            result = count_method(
                status=status,
                premium_only=premium_only,
                verified_only=verified_only,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return int(
                result or 0
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )

    async def statistics(
        self,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> dict[str, int]:

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            statistics_method = getattr(
                repository,
                "statistics",
                None,
            )

            if statistics_method is not None:

                result = statistics_method()

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return dict(
                    result or {}
                )

        total = await self.count(
            db=db
        )

        active = await self.count(
            status=UserStatus.ACTIVE,
            db=db,
        )

        banned = await self.count(
            status=UserStatus.BANNED,
            db=db,
        )

        premium = await self.count(
            premium_only=True,
            db=db,
        )

        verified = await self.count(
            verified_only=True,
            db=db,
        )

        return {
            "total": total,
            "active": active,
            "banned": banned,
            "premium": premium,
            "verified": verified,
        }

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    async def delete(
        self,
        user_id: int,
        *,
        hard: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        user_id = validate_user_id(
            user_id
        )

        if not hard:

            user = await self.set_status(
                user_id,
                UserStatus.DELETED,
                db=db,
            )

            return user is not None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "users",
            None,
        )

        if repository is not None:

            delete_method = getattr(
                repository,
                "delete",
                None,
            )

            if delete_method is not None:

                result = delete_method(
                    user_id
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return bool(
                    result
                )

        orm_model = getattr(
            manager,
            "UserModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as db_session:

                result = await db_session.execute(
                    delete(
                        orm_model
                    ).where(
                        orm_model.id
                        == user_id
                    )
                )

                return bool(
                    result.rowcount
                )

        delete_method = getattr(
            manager,
            "delete_user",
            None,
        )

        if delete_method is not None:

            result = delete_method(
                user_id
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return bool(
                result
            )

        raise RuntimeError(
            "No user persistence adapter is configured."
        )


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[
    UserRepository
] = None


def get_repository(
    db: Optional[
        DatabaseManager
    ] = None,
) -> UserRepository:

    global _default_repository

    if (
        db is not None
        and (
            _default_repository is None
            or _default_repository.db is not db
        )
    ):

        return UserRepository(
            db
        )

    if _default_repository is None:

        _default_repository = (
            UserRepository(
                db
            )
        )

    return _default_repository


# ============================================================================
# Module-level shortcuts
# ============================================================================

async def get_user(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[User]:

    return await get_repository(
        db
    ).get(
        user_id
    )


async def create_user(
    user_id: int,
    **kwargs,
) -> User:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).create(
        user_id,
        **kwargs,
    )


async def upsert_user(
    user_id: int,
    **kwargs,
) -> User:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).upsert(
        user_id,
        **kwargs,
    )


async def get_user_by_username(
    username: str,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[User]:

    return await get_repository(
        db
    ).get_by_username(
        username
    )


async def ban_user(
    user_id: int,
    reason: Optional[str] = None,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[User]:

    return await get_repository(
        db
    ).ban(
        user_id,
        reason,
    )


async def unban_user(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[User]:

    return await get_repository(
        db
    ).unban(
        user_id
    )


async def is_admin(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> bool:

    return await get_repository(
        db
    ).is_admin(
        user_id
    )


async def is_premium(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> bool:

    return await get_repository(
        db
    ).is_premium(
        user_id
    )


async def is_verified(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> bool:

    return await get_repository(
        db
    ).is_verified(
        user_id
    )


async def mark_seen(
    user_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[User]:

    return await get_repository(
        db
    ).mark_seen(
        user_id
    )


async def search_users(
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    db: Optional[
        DatabaseManager
    ] = None,
) -> list[User]:

    return await get_repository(
        db
    ).search(
        query,
        limit=limit,
        offset=offset,
    )


async def list_users(
    *,
    limit: int = 50,
    offset: int = 0,
    status: Optional[
        UserStatus
    ] = None,
    role: Optional[
        UserRole
    ] = None,
    premium_only: bool = False,
    verified_only: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> list[User]:

    return await get_repository(
        db
    ).list_users(
        limit=limit,
        offset=offset,
        status=status,
        role=role,
        premium_only=premium_only,
        verified_only=verified_only,
    )


async def user_count(
    *,
    status: Optional[
        UserStatus
    ] = None,
    premium_only: bool = False,
    verified_only: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> int:

    return await get_repository(
        db
    ).count(
        status=status,
        premium_only=premium_only,
        verified_only=verified_only,
    )


async def user_statistics(
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> dict[str, int]:

    return await get_repository(
        db
    ).statistics(
        db=db
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "UserRepository",
    "get_repository",

    "get_user",
    "create_user",
    "upsert_user",
    "get_user_by_username",

    "ban_user",
    "unban_user",
    "is_admin",
    "is_premium",
    "is_verified",
    "mark_seen",

    "search_users",
    "list_users",
    "user_count",
    "user_statistics",
]