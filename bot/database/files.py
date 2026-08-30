"""
bot.database.files

File repository for Telegram bot file records.

Responsibilities
----------------
- Store Telegram file metadata
- Lookup files by ID / Telegram file ID / unique ID
- Search files
- Track ownership
- Track source chat/message
- Handle expiry
- Soft/hard deletion
- File statistics
- Pagination
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select, update

from bot.database.connection import (
    DatabaseManager,
    get_database_manager,
)
from bot.database.models import (
    File,
    FileStatus,
    utcnow,
    validate_file_size,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _enum_value(value: Any) -> Any:

    if isinstance(
        value,
        FileStatus,
    ):

        return value.value

    return value


def _row_to_file(
    row: Any,
) -> Optional[File]:

    if row is None:
        return None

    if isinstance(
        row,
        File,
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

        return _coerce_file(
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

                return _row_to_file(
                    value
                )

        return _coerce_file(
            mapping
        )

    if isinstance(
        row,
        dict,
    ):

        return _coerce_file(
            row
        )

    return None


def _coerce_file(
    data: dict[str, Any],
) -> File:

    allowed = {
        "id",
        "telegram_file_id",
        "telegram_unique_id",
        "file_name",
        "mime_type",
        "file_size",
        "file_type",
        "status",
        "message_id",
        "chat_id",
        "owner_id",
        "caption",
        "checksum",
        "storage_key",
        "created_at",
        "updated_at",
        "expires_at",
        "metadata",
    }

    values = {
        key: value
        for key, value in data.items()
        if key in allowed
    }

    status = values.get(
        "status"
    )

    if (
        status is not None
        and not isinstance(
            status,
            FileStatus,
        )
    ):

        try:

            values["status"] = FileStatus(
                status
            )

        except ValueError:

            values["status"] = (
                FileStatus.ACTIVE
            )

    return File(
        **values
    )


# ============================================================================
# Repository
# ============================================================================

class FileRepository:

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
        *,
        telegram_file_id: Optional[str] = None,
        telegram_unique_id: Optional[str] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
        status: FileStatus = FileStatus.ACTIVE,
        message_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        owner_id: Optional[int] = None,
        caption: Optional[str] = None,
        checksum: Optional[str] = None,
        storage_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> File:

        file_size = validate_file_size(
            file_size
        )

        now = utcnow()

        record = File(
            telegram_file_id=telegram_file_id,
            telegram_unique_id=telegram_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            file_type=file_type,
            status=status,
            message_id=message_id,
            chat_id=chat_id,
            owner_id=owner_id,
            caption=caption,
            checksum=checksum,
            storage_key=storage_key,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
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
            "files",
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
                    record
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_file(
                        result
                    )
                    or record
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            values = record.to_dict()

            values["status"] = _enum_value(
                values["status"]
            )

            values.pop(
                "id",
                None,
            )

            object_value = orm_model(
                **values
            )

            async with manager.transaction() as db_session:

                db_session.add(
                    object_value
                )

                await db_session.flush()

            result = _row_to_file(
                object_value
            )

            if result is not None:
                return result

            record.id = getattr(
                object_value,
                "id",
                None,
            )

            return record

        insert_method = getattr(
            manager,
            "insert_file",
            None,
        )

        if insert_method is not None:

            result = insert_method(
                record
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_file(
                    result
                )
                or record
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Upsert / deduplication
    # ------------------------------------------------------------------------

    async def upsert(
        self,
        *,
        telegram_file_id: Optional[str] = None,
        telegram_unique_id: Optional[str] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
        message_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        owner_id: Optional[int] = None,
        caption: Optional[str] = None,
        checksum: Optional[str] = None,
        storage_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        metadata: Optional[
            dict[str, Any]
        ] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> File:

        existing = None

        if telegram_file_id:

            existing = await self.get_by_telegram_file_id(
                telegram_file_id,
                db=db,
            )

        if existing is None and telegram_unique_id:

            existing = await self.get_by_unique_id(
                telegram_unique_id,
                db=db,
            )

        if existing is None and checksum:

            existing = await self.get_by_checksum(
                checksum,
                db=db,
            )

        if existing is None:

            return await self.create(
                telegram_file_id=telegram_file_id,
                telegram_unique_id=telegram_unique_id,
                file_name=file_name,
                mime_type=mime_type,
                file_size=file_size,
                file_type=file_type,
                message_id=message_id,
                chat_id=chat_id,
                owner_id=owner_id,
                caption=caption,
                checksum=checksum,
                storage_key=storage_key,
                expires_at=expires_at,
                metadata=metadata,
                db=db,
            )

        values = {}

        for key, value in {
            "telegram_file_id": telegram_file_id,
            "telegram_unique_id": telegram_unique_id,
            "file_name": file_name,
            "mime_type": mime_type,
            "file_size": file_size,
            "file_type": file_type,
            "message_id": message_id,
            "chat_id": chat_id,
            "owner_id": owner_id,
            "caption": caption,
            "checksum": checksum,
            "storage_key": storage_key,
            "expires_at": expires_at,
        }.items():

            if value is not None:

                values[key] = value

        if metadata:

            merged = dict(
                existing.metadata
                or {}
            )

            merged.update(
                metadata
            )

            values[
                "metadata"
            ] = merged

        if values:

            updated = await self.update_fields(
                existing.id,
                values,
                db=db,
            )

            if updated is not None:

                return updated

        return existing

    # ------------------------------------------------------------------------
    # Telegram convenience
    # ------------------------------------------------------------------------

    async def save_telegram_file(
        self,
        telegram_file: Any,
        *,
        message_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        owner_id: Optional[int] = None,
        caption: Optional[str] = None,
        file_type: Optional[str] = None,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> File:

        if telegram_file is None:

            raise ValueError(
                "telegram_file is required."
            )

        file_id = getattr(
            telegram_file,
            "file_id",
            None,
        )

        unique_id = getattr(
            telegram_file,
            "file_unique_id",
            None,
        )

        file_size = getattr(
            telegram_file,
            "file_size",
            None,
        )

        file_name = getattr(
            telegram_file,
            "file_name",
            None,
        )

        mime_type = getattr(
            telegram_file,
            "mime_type",
            None,
        )

        return await self.upsert(
            telegram_file_id=file_id,
            telegram_unique_id=unique_id,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            file_type=file_type,
            message_id=message_id,
            chat_id=chat_id,
            owner_id=owner_id,
            caption=caption,
            db=db,
        )

    # ------------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------------

    async def get(
        self,
        file_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        try:

            file_id = int(
                file_id
            )

        except (
            TypeError,
            ValueError,
        ):

            raise ValueError(
                "file_id must be an integer."
            )

        if file_id <= 0:

            raise ValueError(
                "file_id must be greater than zero."
            )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
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
                    file_id
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_file(
                    result
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.id
                        == file_id
                    )
                )

                return _row_to_file(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_file",
            None,
        )

        if getter is not None:

            result = getter(
                file_id
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_file(
                result
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    async def get_by_telegram_file_id(
        self,
        telegram_file_id: str,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        value = (
            str(
                telegram_file_id
            ).strip()
        )

        if not value:
            return None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
            None,
        )

        if repository is not None:

            getter = getattr(
                repository,
                "get_by_telegram_file_id",
                None,
            )

            if getter is not None:

                result = getter(
                    value
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_file(
                    result
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.telegram_file_id
                        == value
                    )
                )

                return _row_to_file(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_file_by_telegram_id",
            None,
        )

        if getter is not None:

            result = getter(
                value
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_file(
                result
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    async def get_by_unique_id(
        self,
        unique_id: str,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        value = str(
            unique_id
        ).strip()

        if not value:
            return None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
            None,
        )

        if repository is not None:

            getter = getattr(
                repository,
                "get_by_unique_id",
                None,
            )

            if getter is not None:

                result = getter(
                    value
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_file(
                    result
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.telegram_unique_id
                        == value
                    )
                )

                return _row_to_file(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_file_by_unique_id",
            None,
        )

        if getter is not None:

            result = getter(
                value
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_file(
                result
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    async def get_by_checksum(
        self,
        checksum: str,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        value = str(
            checksum
        ).strip()

        if not value:
            return None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
            None,
        )

        if repository is not None:

            getter = getattr(
                repository,
                "get_by_checksum",
                None,
            )

            if getter is not None:

                result = getter(
                    value
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_file(
                    result
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    ).where(
                        orm_model.checksum
                        == value
                    )
                )

                return _row_to_file(
                    result.scalar_one_or_none()
                )

        getter = getattr(
            manager,
            "get_file_by_checksum",
            None,
        )

        if getter is not None:

            result = getter(
                value
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_file(
                result
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    async def update(
        self,
        record: File,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> File:

        if record.id is None:

            raise ValueError(
                "Cannot update a file without an id."
            )

        record.updated_at = utcnow()

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
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
                    record
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return (
                    _row_to_file(
                        result
                    )
                    or record
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            values = record.to_dict()

            values["status"] = _enum_value(
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
                        == record.id
                    )
                    .values(
                        **values
                    )
                )

            return record

        updater = getattr(
            manager,
            "update_file",
            None,
        )

        if updater is not None:

            result = updater(
                record
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return (
                _row_to_file(
                    result
                )
                or record
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    async def update_fields(
        self,
        file_id: int,
        fields: dict[str, Any],
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        try:

            file_id = int(
                file_id
            )

        except (
            TypeError,
            ValueError,
        ):

            raise ValueError(
                "file_id must be an integer."
            )

        if file_id <= 0:

            raise ValueError(
                "file_id must be greater than zero."
            )

        allowed = {
            "telegram_file_id",
            "telegram_unique_id",
            "file_name",
            "mime_type",
            "file_size",
            "file_type",
            "status",
            "message_id",
            "chat_id",
            "owner_id",
            "caption",
            "checksum",
            "storage_key",
            "expires_at",
            "metadata",
        }

        invalid = (
            set(fields)
            - allowed
        )

        if invalid:

            raise ValueError(
                "Unsupported file fields: "
                + ", ".join(
                    sorted(
                        invalid
                    )
                )
            )

        values = dict(
            fields
        )

        if "file_size" in values:

            values["file_size"] = (
                validate_file_size(
                    values["file_size"]
                )
            )

        if "status" in values:

            values["status"] = _enum_value(
                values["status"]
            )

        values[
            "updated_at"
        ] = utcnow()

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
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
                    file_id,
                    values,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return _row_to_file(
                    result
                )

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as db_session:

                await db_session.execute(
                    update(
                        orm_model
                    )
                    .where(
                        orm_model.id
                        == file_id
                    )
                    .values(
                        **values
                    )
                )

            return await self.get(
                file_id,
                db=db,
            )

        updater = getattr(
            manager,
            "update_file_fields",
            None,
        )

        if updater is not None:

            result = updater(
                file_id,
                values,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return _row_to_file(
                result
            )

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------------

    async def set_status(
        self,
        file_id: int,
        status: FileStatus,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        return await self.update_fields(
            file_id,
            {
                "status": status,
            },
            db=db,
        )

    async def soft_delete(
        self,
        file_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        return await self.set_status(
            file_id,
            FileStatus.DELETED,
            db=db,
        )

    async def restore(
        self,
        file_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        return await self.set_status(
            file_id,
            FileStatus.ACTIVE,
            db=db,
        )

    # ------------------------------------------------------------------------
    # Expiry
    # ------------------------------------------------------------------------

    async def set_expiry(
        self,
        file_id: int,
        expires_at: Optional[datetime],
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        return await self.update_fields(
            file_id,
            {
                "expires_at": expires_at,
            },
            db=db,
        )

    async def expire(
        self,
        file_id: int,
        *,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> Optional[File]:

        return await self.set_status(
            file_id,
            FileStatus.EXPIRED,
            db=db,
        )

    async def expire_files(
        self,
        *,
        limit: int = 500,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> int:

        limit = max(
            1,
            min(
                int(limit),
                5000,
            ),
        )

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "expire_files",
                None,
            )

            if method is not None:

                result = method(
                    limit=limit
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
            "FileModel",
            None,
        )

        if orm_model is not None:

            now = utcnow()

            async with manager.transaction() as db_session:

                result = await db_session.execute(
                    update(
                        orm_model
                    )
                    .where(
                        and_(
                            orm_model.expires_at.is_not(
                                None
                            ),
                            orm_model.expires_at
                            <= now,
                            orm_model.status
                            == FileStatus.ACTIVE.value,
                        )
                    )
                    .values(
                        status=FileStatus.EXPIRED.value,
                        updated_at=now,
                    )
                )

                return int(
                    result.rowcount or 0
                )

        method = getattr(
            manager,
            "expire_files",
            None,
        )

        if method is not None:

            result = method(
                limit=limit
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
            "No file persistence adapter is configured."
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
        owner_id: Optional[int] = None,
        active_only: bool = True,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[File]:

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
            "files",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "search",
                None,
            )

            if method is not None:

                result = method(
                    query,
                    limit=limit,
                    offset=offset,
                    owner_id=owner_id,
                    active_only=active_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    record
                    for record in (
                        _row_to_file(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if record is not None
                ]

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            pattern = (
                f"%{query}%"
            )

            conditions = [
                orm_model.file_name.ilike(
                    pattern
                ),
                orm_model.caption.ilike(
                    pattern
                ),
                orm_model.mime_type.ilike(
                    pattern
                ),
                orm_model.file_type.ilike(
                    pattern
                ),
            ]

            if owner_id is not None:

                conditions.append(
                    orm_model.owner_id
                    == int(
                        owner_id
                    )
                )

            if active_only:

                conditions.append(
                    orm_model.status
                    == FileStatus.ACTIVE.value
                )

                conditions.append(
                    or_(
                        orm_model.expires_at.is_(
                            None
                        ),
                        orm_model.expires_at
                        > utcnow(),
                    )
                )

            async with manager.session_context() as db_session:

                result = await db_session.execute(
                    select(
                        orm_model
                    )
                    .where(
                        and_(
                            or_(
                                *conditions[:4]
                            ),
                            *conditions[4:],
                        )
                    )
                    .order_by(
                        orm_model.created_at.desc()
                    )
                    .offset(
                        offset
                    )
                    .limit(
                        limit
                    )
                )

                return [
                    record
                    for row in result.scalars().all()
                    if (
                        record := _row_to_file(
                            row
                        )
                    ) is not None
                ]

        method = getattr(
            manager,
            "search_files",
            None,
        )

        if method is not None:

            result = method(
                query,
                limit=limit,
                offset=offset,
                owner_id=owner_id,
                active_only=active_only,
            )

            if hasattr(
                result,
                "__await__",
            ):

                result = await result

            return [
                record
                for record in (
                    _row_to_file(
                        row
                    )
                    for row in (
                        result
                        or []
                    )
                )
                if record is not None
            ]

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------------

    async def list_files(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        status: Optional[
            FileStatus
        ] = None,
        file_type: Optional[str] = None,
        active_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> list[File]:

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
            "files",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "list_files",
                None,
            )

            if method is not None:

                result = method(
                    limit=limit,
                    offset=offset,
                    owner_id=owner_id,
                    chat_id=chat_id,
                    status=status,
                    file_type=file_type,
                    active_only=active_only,
                )

                if hasattr(
                    result,
                    "__await__",
                ):

                    result = await result

                return [
                    record
                    for record in (
                        _row_to_file(
                            row
                        )
                        for row in (
                            result
                            or []
                        )
                    )
                    if record is not None
                ]

        orm_model = getattr(
            manager,
            "FileModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if owner_id is not None:

                conditions.append(
                    orm_model.owner_id
                    == int(
                        owner_id
                    )
                )

            if chat_id is not None:

                conditions.append(
                    orm_model.chat_id
                    == int(
                        chat_id
                    )
                )

            if status is not None:

                conditions.append(
                    orm_model.status
                    == _enum_value(
                        status
                    )
                )

            if file_type is not None:

                conditions.append(
                    orm_model.file_type
                    == file_type
                )

            if active_only:

                conditions.append(
                    orm_model.status
                    == FileStatus.ACTIVE.value
                )

                conditions.append(
                    or_(
                        orm_model.expires_at.is_(
                            None
                        ),
                        orm_model.expires_at
                        > utcnow(),
                    )
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
                    orm_model.created_at.desc()
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
                    record
                    for row in result.scalars().all()
                    if (
                        record := _row_to_file(
                            row
                        )
                    ) is not None
                ]

        raise RuntimeError(
            "No file persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        owner_id: Optional[int] = None,
        status: Optional[
            FileStatus
        ] = None,
        active_only: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> int:

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
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
                    owner_id=owner_id,
                    status=status,
                    active_only=active_only,
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
            "FileModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if owner_id is not None:

                conditions.append(
                    orm_model.owner_id
                    == int(
                        owner_id
                    )
                )

            if status is not None:

                conditions.append(
                    orm_model.status
                    == _enum_value(
                        status
                    )
                )

            if active_only:

                conditions.append(
                    orm_model.status
                    == FileStatus.ACTIVE.value
                )

                conditions.append(
                    or_(
                        orm_model.expires_at.is_(
                            None
                        ),
                        orm_model.expires_at
                        > utcnow(),
                    )
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

        method = getattr(
            manager,
            "count_files",
            None,
        )

        if method is not None:

            result = method(
                owner_id=owner_id,
                status=status,
                active_only=active_only,
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
            "No file persistence adapter is configured."
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

        total = await self.count(
            db=db
        )

        active = await self.count(
            status=FileStatus.ACTIVE,
            db=db,
        )

        deleted = await self.count(
            status=FileStatus.DELETED,
            db=db,
        )

        expired = await self.count(
            status=FileStatus.EXPIRED,
            db=db,
        )

        return {
            "total": total,
            "active": active,
            "deleted": deleted,
            "expired": expired,
        }

    # ------------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------------

    async def delete(
        self,
        file_id: int,
        *,
        hard: bool = False,
        db: Optional[
            DatabaseManager
        ] = None,
    ) -> bool:

        if not hard:

            result = await self.soft_delete(
                file_id,
                db=db,
            )

            return result is not None

        manager = self._database(
            db
        )

        repository = getattr(
            manager,
            "files",
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
                    file_id
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
            "FileModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as db_session:

                result = await db_session.execute(
                    delete(
                        orm_model
                    ).where(
                        orm_model.id
                        == int(
                            file_id
                        )
                    )
                )

                return bool(
                    result.rowcount
                )

        method = getattr(
            manager,
            "delete_file",
            None,
        )

        if method is not None:

            result = method(
                file_id
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
            "No file persistence adapter is configured."
        )


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[
    FileRepository
] = None


def get_repository(
    db: Optional[
        DatabaseManager
    ] = None,
) -> FileRepository:

    global _default_repository

    if (
        db is not None
        and (
            _default_repository is None
            or _default_repository.db is not db
        )
    ):

        return FileRepository(
            db
        )

    if _default_repository is None:

        _default_repository = (
            FileRepository(
                db
            )
        )

    return _default_repository


# ============================================================================
# Module-level API
# ============================================================================

async def get_file(
    file_id: int,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[File]:

    return await get_repository(
        db
    ).get(
        file_id
    )


async def create_file(
    **kwargs,
) -> File:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).create(
        **kwargs
    )


async def upsert_file(
    **kwargs,
) -> File:

    db = kwargs.pop(
        "db",
        None,
    )

    return await get_repository(
        db
    ).upsert(
        **kwargs
    )


async def get_file_by_telegram_id(
    telegram_file_id: str,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[File]:

    return await get_repository(
        db
    ).get_by_telegram_file_id(
        telegram_file_id,
    )


async def get_file_by_unique_id(
    unique_id: str,
    *,
    db: Optional[
        DatabaseManager
    ] = None,
) -> Optional[File]:

    return await get_repository(
        db
    ).get_by_unique_id(
        unique_id,
    )


async def search_files(
    query: str,
    *,
    limit: int = 20,
    offset: int = 0,
    owner_id: Optional[int] = None,
    active_only: bool = True,
    db: Optional[
        DatabaseManager
    ] = None,
) -> list[File]:

    return await get_repository(
        db
    ).search(
        query,
        limit=limit,
        offset=offset,
        owner_id=owner_id,
        active_only=active_only,
    )


async def delete_file(
    file_id: int,
    *,
    hard: bool = False,
    db: Optional[
        DatabaseManager
    ] = None,
) -> bool:

    return await get_repository(
        db
    ).delete(
        file_id,
        hard=hard,
    )


async def expire_files(
    *,
    limit: int = 500,
    db: Optional[
        DatabaseManager
    ] = None,
) -> int:

    return await get_repository(
        db
    ).expire_files(
        limit=limit,
    )


async def file_statistics(
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
    "FileRepository",
    "get_repository",

    "get_file",
    "create_file",
    "upsert_file",

    "get_file_by_telegram_id",
    "get_file_by_unique_id",

    "search_files",
    "delete_file",
    "expire_files",
    "file_statistics",
]