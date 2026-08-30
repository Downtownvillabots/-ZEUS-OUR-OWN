"""
bot.database.groups

Group repository.

Responsibilities
----------------
- Register Telegram groups
- Update group metadata
- Enable/disable groups
- Track group status
- Lookup by Telegram ID / username
- List groups
- Group statistics
- Membership metadata
- Safe repository-level persistence

The repository keeps database access separate from handlers/services.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select, update

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
)
from bot.database.models import (
    Group,
    GroupStatus,
    utcnow,
    validate_group_id,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Conversion helpers
# ============================================================================

def _enum_value(
    value: Any,
) -> Any:

    if isinstance(
        value,
        GroupStatus,
    ):

        return value.value

    return value


def _row_to_group(
    row: Any,
) -> Optional[Group]:

    if row is None:
        return None

    if isinstance(
        row,
        Group,
    ):

        return row

    if hasattr(
        row,
        "__table__",
    ):

        values = {}

        for column in row.__table__.columns:

            try:

                values[column.name] = getattr(
                    row,
                    column.name,
                )

            except AttributeError:

                continue

        return _coerce_group(
            values
        )

    if hasattr(
        row,
        "_mapping",
    ):

        mapping = dict(
            row._mapping
        )

        if len(mapping) == 1:

            value = next(
                iter(
                    mapping.values()
                )
            )

            if value is not row:

                return _row_to_group(
                    value
                )

        return _coerce_group(
            mapping
        )

    if isinstance(
        row,
        dict,
    ):

        return _coerce_group(
            row
        )

    return None


def _coerce_group(
    data: dict[str, Any],
) -> Group:

    allowed = {
        "id",
        "title",
        "username",
        "group_type",
        "status",
        "is_enabled",
        "is_verified",
        "member_count",
        "added_by",
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
            "Group row does not contain id."
        )

    status = values.get(
        "status"
    )

    if (
        status is not None
        and not isinstance(
            status,
            GroupStatus,
        )
    ):

        try:

            values["status"] = GroupStatus(
                status
            )

        except ValueError:

            values["status"] = (
                GroupStatus.ACTIVE
            )

    return Group(
        **values
    )


# ============================================================================
# Repository
# ============================================================================

class GroupRepository:
    """
    Repository for Telegram groups.
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
    # Create
    # ------------------------------------------------------------------------

    async def create(
        self,
        group_id: int,
        *,
        title: Optional[str] = None,
        username: Optional[str] = None,
        group_type: Optional[str] = None,
        status: GroupStatus = GroupStatus.ACTIVE,
        is_enabled: bool = True,
        is_verified: bool = False,
        member_count: Optional[int] = None,
        added_by: Optional[int] = None,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Group:

        group_id = validate_group_id(
            group_id
        )

        now = utcnow()

        group = Group(
            id=group_id,
            title=title,
            username=username,
            group_type=group_type,
            status=status,
            is_enabled=bool(
                is_enabled
            ),
            is_verified=bool(
                is_verified
            ),
            member_count=member_count,
            added_by=added_by,
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

        repository = getattr(
            manager,
            "groups",
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
                    group
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_group(
                        result
                    )
                    or group
                )

        orm_model = getattr(
            manager,
            "GroupModel",
            None,
        )

        if orm_model is not None:

            values = group.to_dict()

            values[
                "status"
            ] = _enum_value(
                values["status"]
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
                _row_to_group(
                    object_value
                )
                or group
            )

        insert_method = getattr(
            manager,
            "insert_group",
            None,
        )

        if insert_method is not None:

            result = insert_method(
                group
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_group(
                    result
                )
                or group
            )

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------------

    async def upsert(
        self,
        group_id: int,
        *,
        title: Optional[str] = None,
        username: Optional[str] = None,
        group_type: Optional[str] = None,
        member_count: Optional[int] = None,
        added_by: Optional[int] = None,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        preserve_status: bool = True,
        preserve_enabled: bool = True,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Group:

        group_id = validate_group_id(
            group_id
        )

        existing = await self.get(
            group_id,
            db=db,
        )

        if existing is None:

            return await self.create(
                group_id,
                title=title,
                username=username,
                group_type=group_type,
                member_count=member_count,
                added_by=added_by,
                metadata=metadata,
                db=db,
            )

        existing.title = title

        existing.username = (
            username
        )

        existing.group_type = (
            group_type
        )

        if member_count is not None:

            existing.member_count = (
                max(
                    0,
                    int(
                        member_count
                    ),
                )
            )

        if added_by is not None:

            existing.added_by = (
                added_by
            )

        if metadata:

            existing.metadata.update(
                metadata
            )

        if not preserve_status:

            existing.status = (
                GroupStatus.ACTIVE
            )

        if not preserve_enabled:

            existing.is_enabled = True

        existing.updated_at = utcnow()

        await self.update(
            existing,
            db=db,
        )

        return existing

    async def upsert_telegram_chat(
        self,
        chat: Any,
        *,
        added_by: Optional[int] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Group:

        if chat is None:

            raise ValueError(
                "chat is required."
            )

        group_id = getattr(
            chat,
            "id",
            None,
        )

        if group_id is None:

            raise ValueError(
                "Telegram chat does not contain an id."
            )

        chat_type = getattr(
            chat,
            "type",
            None,
        )

        if hasattr(
            chat_type,
            "value",
        ):

            chat_type = (
                chat_type.value
            )

        return await self.upsert(
            int(
                group_id
            ),
            title=getattr(
                chat,
                "title",
                None,
            ),
            username=getattr(
                chat,
                "username",
                None,
            ),
            group_type=(
                str(
                    chat_type
                )
                if chat_type is not None
                else None
            ),
            added_by=added_by,
            db=db,
        )

    # ------------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------------

    async def get(
        self,
        group_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[Group]:

        group_id = validate_group_id(
            group_id
        )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "groups",
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
                    group_id
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_group(
                    result
                )

        orm_model = getattr(
            manager,
            "GroupModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.id
                        == group_id
                    )
                )

                return _row_to_group(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_group",
            None,
        )

        if getter is not None:

            result = getter(
                group_id
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_group(
                result
            )

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    async def exists(
        self,
        group_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        return (
            await self.get(
                group_id,
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
    ) -> Optional[Group]:

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
            "groups",
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

                return _row_to_group(
                    result
                )

        orm_model = getattr(
            manager,
            "GroupModel",
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

                return _row_to_group(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_group_by_username",
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

            return _row_to_group(
                result
            )

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    async def update(
        self,
        group: Group,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Group:

        group.id = validate_group_id(
            group.id
        )

        group.updated_at = utcnow()

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "groups",
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
                    group
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_group(
                        result
                    )
                    or group
                )

        orm_model = getattr(
            manager,
            "GroupModel",
            None,
        )

        if orm_model is not None:

            values = group.to_dict()

            values[
                "status"
            ] = _enum_value(
                values["status"]
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
                        == group.id
                    )
                    .values(
                        **values
                    )
                )

            return group

        updater = getattr(
            manager,
            "update_group",
            None,
        )

        if updater is not None:

            result = updater(
                group
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_group(
                    result
                )
                or group
            )

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    async def update_fields(
        self,
        group_id: int,
        fields: dict[str, Any],
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[Group]:

        group_id = validate_group_id(
            group_id
        )

        if not fields:

            return await self.get(
                group_id,
                db=db,
            )

        allowed = {
            "title",
            "username",
            "group_type",
            "status",
            "is_enabled",
            "is_verified",
            "member_count",
            "added_by",
            "metadata",
        }

        invalid = (
            set(fields)
            - allowed
        )

        if invalid:

            raise ValueError(
                "Unsupported group fields: "
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
            "groups",
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
                    group_id,
                    values,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_group(
                    result
                )

        orm_model = getattr(
            manager,
            "GroupModel",
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
                        == group_id
                    )
                    .values(
                        **values
                    )
                )

            return await self.get(
                group_id,
                db=db,
            )

        updater = getattr(
            manager,
            "update_group_fields",
            None,
        )

        if updater is not None:

            result = updater(
                group_id,
                values,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_group(
                result
            )

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------------

    async def enable(
        self,
        group_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[Group]:

        return await self.update_fields(
            group_id,
            {
                "is_enabled": True,
                "status": GroupStatus.ACTIVE,
            },
            db=db,
        )

    async def disable(
        self,
        group_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ):

        return await self.update_fields(
            group_id,
            {
                "is_enabled": False,
                "status": GroupStatus.DISABLED,
            },
            db=db,
        )

    async def mark_left(
        self,
        group_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ):

        return await self.update_fields(
            group_id,
            {
                "is_enabled": False,
                "status": GroupStatus.LEFT,
            },
            db=db,
        )

    async def set_verified(
        self,
        group_id: int,
        verified: bool,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ):

        return await self.update_fields(
            group_id,
            {
                "is_verified": bool(
                    verified
                ),
            },
            db=db,
        )

    async def set_member_count(
        self,
        group_id: int,
        member_count: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ):

        member_count = max(
            0,
            int(
                member_count
            ),
        )

        return await self.update_fields(
            group_id,
            {
                "member_count": member_count,
            },
            db=db,
        )

    # ------------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        enabled_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[Group]:

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
            "groups",
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
                    enabled_only=enabled_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    group
                    for group in (
                        _row_to_group(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if group is not None
                ]

        orm_model = getattr(
            manager,
            "GroupModel",
            None,
        )

        if orm_model is not None:

            pattern = (
                f"%{query}%"
            )

            conditions = [
                orm_model.title.ilike(
                    pattern
                ),
                orm_model.username.ilike(
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

            if enabled_only:

                conditions.append(
                    orm_model.is_enabled
                    == True
                )

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    )
                    .where(
                        and_(
                            or_(
                                *conditions[:3]
                            ),
                            *conditions[3:],
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
                    group
                    for row in result.scalars().all()
                    if (
                        group := _row_to_group(
                            row
                        )
                    ) is not None
                ]

        search_method = getattr(
            manager,
            "search_groups",
            None,
        )

        if search_method is not None:

            result = search_method(
                query,
                limit=limit,
                offset=offset,
                enabled_only=enabled_only,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return [
                group
                for group in (
                    _row_to_group(
                        row
                    )
                    for row in (
                        result
                        or []
                    )
                )
                if group is not None
            ]

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------------

    async def list_groups(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[
            GroupStatus
        ] = None,
        enabled_only: bool = False,
        verified_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[Group]:

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
            "groups",
            None,
        )

        if repository is not None:

            list_method = getattr(
                repository,
                "list_groups",
                None,
            )

            if list_method is not None:

                result = list_method(
                    limit=limit,
                    offset=offset,
                    status=status,
                    enabled_only=enabled_only,
                    verified_only=verified_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    group
                    for group in (
                        _row_to_group(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if group is not None
                ]

        orm_model = getattr(
            manager,
            "GroupModel",
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

            if enabled_only:

                conditions.append(
                    orm_model.is_enabled
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

                return [
                    group
                    for row in result.scalars().all()
                    if (
                        group := _row_to_group(
                            row
                        )
                    ) is not None
                ]

        raise RuntimeError(
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        status: Optional[
            GroupStatus
        ] = None,
        enabled_only: bool = False,
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
            "groups",
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
                    enabled_only=enabled_only,
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
            "GroupModel",
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

            if enabled_only:

                conditions.append(
                    orm_model.is_enabled
                    == True
                )

            if verified_only:

                conditions.append(
                    orm_model.is_verified
                    == True
                )

            statement = (
                select(
                    func.count()
                )
                .select_from(
                    orm_model
                )
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
            "count_groups",
            None,
        )

        if count_method is not None:

            result = count_method(
                status=status,
                enabled_only=enabled_only,
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
            "No group persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

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
            "groups",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "statistics",
                None,
            )

            if method is not None:

                result = method()

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
            status=GroupStatus.ACTIVE,
            db=db,
        )

        enabled = await self.count(
            enabled_only=True,
            db=db,
        )

        verified = await self.count(
            verified_only=True,
            db=db,
        )

        return {
            "total": total,
            "active": active,
            "enabled": enabled,
            "verified": verified,
        }

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    async def delete(
        self,
        group_id: int,
        *,
        hard: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        group_id = validate_group_id(
            group_id
        )

        if not hard:

            result = await self.update_fields(
                group_id,
                {
                    "status": (
                        GroupStatus.DELETED
                    ),
                    "is_enabled": False,
                },
                db=db,
            )

            return result is not None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "groups",
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
                    group_id
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
            "GroupModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as db_session:

                result = await db_session.execute(
                    delete(
                        orm_model
                    ).where(
                        orm_model.id
                        == group_id
                    )
                )

                return bool(
                    result.rowcount
                )

        delete_method = getattr(
            manager,
            "delete_group",
            None,
        )

        if delete_method is not None:

            result = delete_method(
                group_id
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
            "No group persistence adapter is configured."
        )


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[
    GroupRepository
] = None


def get_repository(
    db: Optional[
        DatabaseManager
    ] = None,
) -> GroupRepository:

    global _default_repository

    if (
        db is not None
        and (
            _default_repository is None
            or _default_repository.db is not db
        )
    ):

        return GroupRepository(
            db
        )

    if _default_repository is None:

        _default_repository = (
            GroupRepository(
                db
            )
        )

    return _default_repository


# ============================================================================
# Module-level shortcuts
# ============================================================================

async def get_group(
    group_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[Group]:

    return await get_repository(
        db
    ).get(
        group_id
    )


async def create_group(
    group_id: int,
    **kwargs,
) -> Group:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).create(
        group_id,
        **kwargs,
    )


async def upsert_group(
    group_id: int,
    **kwargs,
) -> Group:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).upsert(
        group_id,
        **kwargs,
    )


async def get_group_by_username(
    username: str,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[Group]:

    return await get_repository(
        db
    ).get_by_username(
        username
    )


async def enable_group(
    group_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[Group]:

    return await get_repository(
        db
    ).enable(
        group_id
    )


async def disable_group(
    group_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[Group]:

    return await get_repository(
        db
    ).disable(
        group_id
    )


async def search_groups(
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    enabled_only: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> list[Group]:

    return await get_repository(
        db
    ).search(
        query,
        limit=limit,
        offset=offset,
        enabled_only=enabled_only,
    )


async def list_groups(
    *,
    limit: int = 50,
    offset: int = 0,
    status: Optional[
        GroupStatus
    ] = None,
    enabled_only: bool = False,
    verified_only: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> list[Group]:

    return await get_repository(
        db
    ).list_groups(
        limit=limit,
        offset=offset,
        status=status,
        enabled_only=enabled_only,
        verified_only=verified_only,
    )


async def group_count(
    *,
    status: Optional[
        GroupStatus
    ] = None,
    enabled_only: bool = False,
    verified_only: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> int:

    return await get_repository(
        db
    ).count(
        status=status,
        enabled_only=enabled_only,
        verified_only=verified_only,
    )


async def group_statistics(
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
    "GroupRepository",
    "get_repository",

    "get_group",
    "create_group",
    "upsert_group",
    "get_group_by_username",

    "enable_group",
    "disable_group",

    "search_groups",
    "list_groups",
    "group_count",
    "group_statistics",
]