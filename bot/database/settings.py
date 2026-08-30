"""
bot.database.settings

Persistent application/group/user settings.

Supports:
- Global settings
- Group settings
- User settings
- Typed values
- Defaults
- Bulk updates
- Delete/reset
- Namespaced keys
"""

from __future__ import annotations

import logging
import json
from typing import Any, Optional

from sqlalchemy import and_, delete, select, update

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
)
from bot.database.models import Setting, utcnow

logger = logging.getLogger(__name__)


# ============================================================================
# Value helpers
# ============================================================================

def serialize_value(
    value: Any,
) -> str:

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def deserialize_value(
    value: Any,
) -> Any:

    if value is None:
        return None

    if not isinstance(value, str):
        return value

    try:
        return json.loads(value)
    except (
        json.JSONDecodeError,
        TypeError,
    ):
        return value


# ============================================================================
# Repository
# ============================================================================

class SettingsRepository:

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
    # Internal lookup
    # ------------------------------------------------------------------------

    async def _get_record(
        self,
        *,
        key: str,
        scope: str,
        scope_id: Optional[int],
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Setting]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "SettingModel",
            None,
        )

        if orm_model is not None:

            conditions = [
                orm_model.key == key,
                orm_model.scope == scope,
            ]

            if scope_id is None:

                conditions.append(
                    orm_model.scope_id.is_(None)
                )

            else:

                conditions.append(
                    orm_model.scope_id
                    == int(scope_id)
                )

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model).where(
                        and_(*conditions)
                    )
                )

                return result.scalar_one_or_none()

        repository = getattr(
            manager,
            "settings",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "get_record",
                None,
            )

            if method is not None:

                result = method(
                    key=key,
                    scope=scope,
                    scope_id=scope_id,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return result

        raise RuntimeError(
            "No settings persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------------

    async def get(
        self,
        key: str,
        default: Any = None,
        *,
        scope: str = "global",
        scope_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Any:

        key = str(key).strip()

        if not key:
            return default

        record = await self._get_record(
            key=key,
            scope=scope,
            scope_id=scope_id,
            db=db,
        )

        if record is None:
            return default

        value = getattr(
            record,
            "value",
            None,
        )

        return deserialize_value(
            value
        )

    # ------------------------------------------------------------------------
    # Set
    # ------------------------------------------------------------------------

    async def set(
        self,
        key: str,
        value: Any,
        *,
        scope: str = "global",
        scope_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Setting:

        key = str(key).strip()
        scope = str(scope).strip()

        if not key:
            raise ValueError(
                "Setting key cannot be empty."
            )

        if not scope:
            raise ValueError(
                "Setting scope cannot be empty."
            )

        manager = self._database(db)

        serialized = serialize_value(
            value
        )

        existing = await self._get_record(
            key=key,
            scope=scope,
            scope_id=scope_id,
            db=db,
        )

        if existing is not None:

            orm_model = getattr(
                manager,
                "SettingModel",
                None,
            )

            if orm_model is not None:

                async with manager.transaction() as session:

                    await session.execute(
                        update(orm_model)
                        .where(
                            orm_model.id
                            == existing.id
                        )
                        .values(
                            value=serialized,
                            updated_at=utcnow(),
                        )
                    )

                updated = await self._get_record(
                    key=key,
                    scope=scope,
                    scope_id=scope_id,
                    db=db,
                )

                return updated

            repository = getattr(
                manager,
                "settings",
                None,
            )

            if repository is not None:

                method = getattr(
                    repository,
                    "set",
                    None,
                )

                if method is not None:

                    result = method(
                        key=key,
                        value=serialized,
                        scope=scope,
                        scope_id=scope_id,
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):

                        result = await result

                    return result

        setting = Setting(
            key=key,
            value=serialized,
            scope=scope,
            scope_id=scope_id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )

        orm_model = getattr(
            manager,
            "SettingModel",
            None,
        )

        if orm_model is not None:

            values = setting.to_dict()

            values.pop(
                "id",
                None,
            )

            object_value = orm_model(
                **values
            )

            async with manager.transaction() as session:

                session.add(
                    object_value
                )

                await session.flush()

            return object_value

        repository = getattr(
            manager,
            "settings",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "create",
                None,
            )

            if method is not None:

                result = method(setting)

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return result or setting

        method = getattr(
            manager,
            "set_setting",
            None,
        )

        if method is not None:

            result = method(
                key=key,
                value=serialized,
                scope=scope,
                scope_id=scope_id,
            )

            if hasattr(result, "__await__"):
                result = await result

            return result

        raise RuntimeError(
            "No settings persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get group setting
    # ------------------------------------------------------------------------

    async def get_group(
        self,
        group_id: int,
        key: str,
        default: Any = None,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Any:

        return await self.get(
            key,
            default,
            scope="group",
            scope_id=int(group_id),
            db=db,
        )

    async def set_group(
        self,
        group_id: int,
        key: str,
        value: Any,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Setting:

        return await self.set(
            key,
            value,
            scope="group",
            scope_id=int(group_id),
            db=db,
        )

    # ------------------------------------------------------------------------
    # Get user setting
    # ------------------------------------------------------------------------

    async def get_user(
        self,
        user_id: int,
        key: str,
        default: Any = None,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Any:

        return await self.get(
            key,
            default,
            scope="user",
            scope_id=int(user_id),
            db=db,
        )

    async def set_user(
        self,
        user_id: int,
        key: str,
        value: Any,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Setting:

        return await self.set(
            key,
            value,
            scope="user",
            scope_id=int(user_id),
            db=db,
        )

    # ------------------------------------------------------------------------
    # Global setting
    # ------------------------------------------------------------------------

    async def get_global(
        self,
        key: str,
        default: Any = None,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Any:

        return await self.get(
            key,
            default,
            scope="global",
            scope_id=None,
            db=db,
        )

    async def set_global(
        self,
        key: str,
        value: Any,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Setting:

        return await self.set(
            key,
            value,
            scope="global",
            scope_id=None,
            db=db,
        )

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    async def delete(
        self,
        key: str,
        *,
        scope: str = "global",
        scope_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> bool:

        manager = self._database(db)

        record = await self._get_record(
            key=key,
            scope=scope,
            scope_id=scope_id,
            db=db,
        )

        if record is None:
            return False

        orm_model = getattr(
            manager,
            "SettingModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                result = await session.execute(
                    delete(orm_model).where(
                        orm_model.id
                        == record.id
                    )
                )

                return bool(
                    result.rowcount
                )

        repository = getattr(
            manager,
            "settings",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "delete",
                None,
            )

            if method is not None:

                result = method(
                    key=key,
                    scope=scope,
                    scope_id=scope_id,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return bool(result)

        raise RuntimeError(
            "No settings persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Bulk get
    # ------------------------------------------------------------------------

    async def all(
        self,
        *,
        scope: str = "global",
        scope_id: Optional[int] = None,
        prefix: Optional[str] = None,
        db: Optional[DatabaseManager] = None,
    ) -> dict[str, Any]:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "SettingModel",
            None,
        )

        if orm_model is not None:

            conditions = [
                orm_model.scope == scope,
            ]

            if scope_id is None:

                conditions.append(
                    orm_model.scope_id.is_(None)
                )

            else:

                conditions.append(
                    orm_model.scope_id
                    == int(scope_id)
                )

            if prefix:

                conditions.append(
                    orm_model.key.startswith(
                        prefix
                    )
                )

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model)
                    .where(and_(*conditions))
                    .order_by(
                        orm_model.key.asc()
                    )
                )

                output = {}

                for record in result.scalars().all():

                    output[
                        record.key
                    ] = deserialize_value(
                        record.value
                    )

                return output

        repository = getattr(
            manager,
            "settings",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "all",
                None,
            )

            if method is not None:

                result = method(
                    scope=scope,
                    scope_id=scope_id,
                    prefix=prefix,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return {
                    key: deserialize_value(value)
                    for key, value in (
                        result or {}
                    ).items()
                }

        raise RuntimeError(
            "No settings persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Reset scope
    # ------------------------------------------------------------------------

    async def reset_scope(
        self,
        *,
        scope: str,
        scope_id: Optional[int] = None,
        db: Optional[DatabaseManager] = None,
    ) -> int:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "SettingModel",
            None,
        )

        if orm_model is not None:

            conditions = [
                orm_model.scope == scope,
            ]

            if scope_id is None:

                conditions.append(
                    orm_model.scope_id.is_(None)
                )

            else:

                conditions.append(
                    orm_model.scope_id
                    == int(scope_id)
                )

            async with manager.transaction() as session:

                result = await session.execute(
                    delete(orm_model).where(
                        and_(*conditions)
                    )
                )

                return int(
                    result.rowcount or 0
                )

        repository = getattr(
            manager,
            "settings",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "reset_scope",
                None,
            )

            if method is not None:

                result = method(
                    scope=scope,
                    scope_id=scope_id,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return int(result or 0)

        raise RuntimeError(
            "No settings persistence adapter is configured."
        )


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[
    SettingsRepository
] = None


def get_repository(
    db: Optional[DatabaseManager] = None,
) -> SettingsRepository:

    global _default_repository

    if db is not None:
        return SettingsRepository(db)

    if _default_repository is None:
        _default_repository = SettingsRepository()

    return _default_repository


# ============================================================================
# Module-level shortcuts
# ============================================================================

async def get_setting(
    key: str,
    default: Any = None,
    *,
    scope: str = "global",
    scope_id: Optional[int] = None,
    db: Optional[DatabaseManager] = None,
) -> Any:

    return await get_repository(db).get(
        key,
        default,
        scope=scope,
        scope_id=scope_id,
    )


async def set_setting(
    key: str,
    value: Any,
    *,
    scope: str = "global",
    scope_id: Optional[int] = None,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).set(
        key,
        value,
        scope=scope,
        scope_id=scope_id,
    )


async def get_group_setting(
    group_id: int,
    key: str,
    default: Any = None,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).get_group(
        group_id,
        key,
        default,
    )


async def set_group_setting(
    group_id: int,
    key: str,
    value: Any,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).set_group(
        group_id,
        key,
        value,
    )


async def get_user_setting(
    user_id: int,
    key: str,
    default: Any = None,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).get_user(
        user_id,
        key,
        default,
    )


async def set_user_setting(
    user_id: int,
    key: str,
    value: Any,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).set_user(
        user_id,
        key,
        value,
    )


async def get_global_setting(
    key: str,
    default: Any = None,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).get_global(
        key,
        default,
    )


async def set_global_setting(
    key: str,
    value: Any,
    *,
    db: Optional[DatabaseManager] = None,
):

    return await get_repository(db).set_global(
        key,
        value,
    )


__all__ = [
    "SettingsRepository",
    "get_repository",

    "serialize_value",
    "deserialize_value",

    "get_setting",
    "set_setting",

    "get_group_setting",
    "set_group_setting",

    "get_user_setting",
    "set_user_setting",

    "get_global_setting",
    "set_global_setting",
]