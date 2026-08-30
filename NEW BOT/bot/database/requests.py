"""
bot.database.requests

Request repository.

Tracks user operations such as:
    pending -> processing -> completed
                         -> failed
                         -> cancelled

A request can represent:
- movie/file search
- file retrieval
- delivery request
- verification request
- admin operation
- generic bot operation
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
    Request,
    RequestStatus,
    utcnow,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _enum_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _request_from_row(row: Any) -> Optional[Request]:

    if row is None:
        return None

    if isinstance(row, Request):
        return row

    if hasattr(row, "__table__"):
        values = {}

        for column in row.__table__.columns:
            try:
                values[column.name] = getattr(
                    row,
                    column.name,
                )
            except AttributeError:
                pass

        return Request(**values)

    if hasattr(row, "_mapping"):
        mapping = dict(row._mapping)

        if len(mapping) == 1:
            value = next(iter(mapping.values()))

            if isinstance(value, Request):
                return value

        return Request(
            **{
                key: value
                for key, value in mapping.items()
                if key in {
                    "id",
                    "user_id",
                    "chat_id",
                    "message_id",
                    "request_type",
                    "query",
                    "status",
                    "file_id",
                    "result_id",
                    "error",
                    "started_at",
                    "completed_at",
                    "created_at",
                    "updated_at",
                    "metadata",
                }
            }
        )

    if isinstance(row, dict):
        return Request(
            **{
                key: value
                for key, value in row.items()
                if key in {
                    "id",
                    "user_id",
                    "chat_id",
                    "message_id",
                    "request_type",
                    "query",
                    "status",
                    "file_id",
                    "result_id",
                    "error",
                    "started_at",
                    "completed_at",
                    "created_at",
                    "updated_at",
                    "metadata",
                }
            }
        )

    return None


# ============================================================================
# Repository
# ============================================================================

class RequestRepository:

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
    # Create
    # ------------------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        request_type: str,
        query: Optional[str] = None,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        file_id: Optional[int] = None,
        result_id: Optional[str] = None,
        status: RequestStatus = RequestStatus.PENDING,
        metadata: Optional[dict[str, Any]] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Request:

        now = utcnow()

        request = Request(
            user_id=int(user_id),
            chat_id=chat_id,
            message_id=message_id,
            request_type=str(request_type),
            query=query,
            status=status,
            file_id=file_id,
            result_id=result_id,
            error=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        manager = self._database(db)

        repository = getattr(
            manager,
            "requests",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "create",
                None,
            )

            if method is not None:

                result = method(request)

                if hasattr(result, "__await__"):
                    result = await result

                return _request_from_row(result) or request

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            values = request.to_dict()

            values["status"] = _enum_value(
                values["status"]
            )

            values.pop("id", None)

            object_value = orm_model(
                **values
            )

            async with manager.transaction() as session:

                session.add(object_value)
                await session.flush()

            return (
                _request_from_row(object_value)
                or request
            )

        method = getattr(
            manager,
            "insert_request",
            None,
        )

        if method is not None:

            result = method(request)

            if hasattr(result, "__await__"):
                result = await result

            return _request_from_row(result) or request

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------------

    async def get(
        self,
        request_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        manager = self._database(db)

        repository = getattr(
            manager,
            "requests",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "get",
                None,
            )

            if method is not None:

                result = method(int(request_id))

                if hasattr(result, "__await__"):
                    result = await result

                return _request_from_row(result)

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model).where(
                        orm_model.id == int(request_id)
                    )
                )

                return _request_from_row(
                    result.scalar_one_or_none()
                )

        method = getattr(
            manager,
            "get_request",
            None,
        )

        if method is not None:

            result = method(int(request_id))

            if hasattr(result, "__await__"):
                result = await result

            return _request_from_row(result)

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------------

    async def update_fields(
        self,
        request_id: int,
        fields: dict[str, Any],
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        allowed = {
            "chat_id",
            "message_id",
            "request_type",
            "query",
            "status",
            "file_id",
            "result_id",
            "error",
            "started_at",
            "completed_at",
            "metadata",
        }

        invalid = set(fields) - allowed

        if invalid:
            raise ValueError(
                "Unsupported request fields: "
                + ", ".join(sorted(invalid))
            )

        values = dict(fields)
        values["updated_at"] = utcnow()

        if "status" in values:
            values["status"] = _enum_value(
                values["status"]
            )

        manager = self._database(db)

        repository = getattr(
            manager,
            "requests",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "update_fields",
                None,
            )

            if method is not None:

                result = method(
                    int(request_id),
                    values,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return _request_from_row(result)

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                await session.execute(
                    update(orm_model)
                    .where(
                        orm_model.id == int(request_id)
                    )
                    .values(**values)
                )

            return await self.get(
                request_id,
                db=db,
            )

        method = getattr(
            manager,
            "update_request_fields",
            None,
        )

        if method is not None:

            result = method(
                int(request_id),
                values,
            )

            if hasattr(result, "__await__"):
                result = await result

            return _request_from_row(result)

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------------

    async def start(
        self,
        request_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        return await self.update_fields(
            request_id,
            {
                "status": RequestStatus.PROCESSING,
                "started_at": utcnow(),
                "error": None,
            },
            db=db,
        )

    async def complete(
        self,
        request_id: int,
        *,
        result_id: Optional[str] = None,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        fields = {
            "status": RequestStatus.COMPLETED,
            "completed_at": utcnow(),
            "error": None,
        }

        if result_id is not None:
            fields["result_id"] = result_id

        return await self.update_fields(
            request_id,
            fields,
            db=db,
        )

    async def fail(
        self,
        request_id: int,
        error: str,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        return await self.update_fields(
            request_id,
            {
                "status": RequestStatus.FAILED,
                "completed_at": utcnow(),
                "error": str(error)[:4000],
            },
            db=db,
        )

    async def cancel(
        self,
        request_id: int,
        reason: Optional[str] = None,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> Optional[Request]:

        return await self.update_fields(
            request_id,
            {
                "status": RequestStatus.CANCELLED,
                "completed_at": utcnow(),
                "error": reason,
            },
            db=db,
        )

    # ------------------------------------------------------------------------
    # User requests
    # ------------------------------------------------------------------------

    async def list_user_requests(
        self,
        user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[RequestStatus] = None,
        db: Optional[DatabaseManager] = None,
    ) -> list[Request]:

        manager = self._database(db)

        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            conditions = [
                orm_model.user_id == int(user_id)
            ]

            if status is not None:
                conditions.append(
                    orm_model.status
                    == _enum_value(status)
                )

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model)
                    .where(and_(*conditions))
                    .order_by(
                        orm_model.created_at.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )

                return [
                    request
                    for row in result.scalars().all()
                    if (
                        request := _request_from_row(row)
                    ) is not None
                ]

        repository = getattr(
            manager,
            "requests",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "list_user_requests",
                None,
            )

            if method is not None:

                result = method(
                    int(user_id),
                    limit=limit,
                    offset=offset,
                    status=status,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return [
                    request
                    for row in result or []
                    if (
                        request := _request_from_row(row)
                    ) is not None
                ]

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Pending requests
    # ------------------------------------------------------------------------

    async def list_pending(
        self,
        *,
        limit: int = 100,
        db: Optional[DatabaseManager] = None,
    ) -> list[Request]:

        manager = self._database(db)

        limit = max(1, min(int(limit), 500))

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            async with manager.session_context() as session:

                result = await session.execute(
                    select(orm_model)
                    .where(
                        orm_model.status
                        == _enum_value(
                            RequestStatus.PENDING
                        )
                    )
                    .order_by(
                        orm_model.created_at.asc()
                    )
                    .limit(limit)
                )

                return [
                    request
                    for row in result.scalars().all()
                    if (
                        request := _request_from_row(row)
                    ) is not None
                ]

        repository = getattr(
            manager,
            "requests",
            None,
        )

        if repository is not None:

            method = getattr(
                repository,
                "list_pending",
                None,
            )

            if method is not None:

                result = method(limit=limit)

                if hasattr(result, "__await__"):
                    result = await result

                return [
                    request
                    for row in result or []
                    if (
                        request := _request_from_row(row)
                    ) is not None
                ]

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    # ------------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------------

    async def count(
        self,
        *,
        user_id: Optional[int] = None,
        status: Optional[RequestStatus] = None,
        request_type: Optional[str] = None,
        db: Optional[DatabaseManager] = None,
    ) -> int:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            conditions = []

            if user_id is not None:
                conditions.append(
                    orm_model.user_id == int(user_id)
                )

            if status is not None:
                conditions.append(
                    orm_model.status
                    == _enum_value(status)
                )

            if request_type is not None:
                conditions.append(
                    orm_model.request_type
                    == request_type
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

                return int(result.scalar() or 0)

        repository = getattr(
            manager,
            "requests",
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
                    user_id=user_id,
                    status=status,
                    request_type=request_type,
                )

                if hasattr(result, "__await__"):
                    result = await result

                return int(result or 0)

        raise RuntimeError(
            "No request persistence adapter is configured."
        )

    async def statistics(
        self,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> dict[str, int]:

        return {
            "total": await self.count(db=db),
            "pending": await self.count(
                status=RequestStatus.PENDING,
                db=db,
            ),
            "processing": await self.count(
                status=RequestStatus.PROCESSING,
                db=db,
            ),
            "completed": await self.count(
                status=RequestStatus.COMPLETED,
                db=db,
            ),
            "failed": await self.count(
                status=RequestStatus.FAILED,
                db=db,
            ),
            "cancelled": await self.count(
                status=RequestStatus.CANCELLED,
                db=db,
            ),
        }

    # ------------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------------

    async def delete(
        self,
        request_id: int,
        *,
        db: Optional[DatabaseManager] = None,
    ) -> bool:

        manager = self._database(db)

        orm_model = getattr(
            manager,
            "RequestModel",
            None,
        )

        if orm_model is not None:

            async with manager.transaction() as session:

                result = await session.execute(
                    delete(orm_model).where(
                        orm_model.id
                        == int(request_id)
                    )
                )

                return bool(result.rowcount)

        repository = getattr(
            manager,
            "requests",
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
                    int(request_id)
                )

                if hasattr(result, "__await__"):
                    result = await result

                return bool(result)

        raise RuntimeError(
            "No request persistence adapter is configured."
        )


# ============================================================================
# Global repository
# ============================================================================

_default_repository: Optional[RequestRepository] = None


def get_repository(
    db: Optional[DatabaseManager] = None,
) -> RequestRepository:

    global _default_repository

    if db is not None:
        return RequestRepository(db)

    if _default_repository is None:
        _default_repository = RequestRepository()

    return _default_repository


# ============================================================================
# Shortcuts
# ============================================================================

async def create_request(**kwargs) -> Request:

    db = kwargs.pop("db", None)

    return await get_repository(db).create(
        **kwargs
    )


async def get_request(
    request_id: int,
    *,
    db: Optional[DatabaseManager] = None,
) -> Optional[Request]:

    return await get_repository(db).get(
        request_id
    )


async def start_request(
    request_id: int,
    *,
    db: Optional[DatabaseManager] = None,
) -> Optional[Request]:

    return await get_repository(db).start(
        request_id
    )


async def complete_request(
    request_id: int,
    *,
    result_id: Optional[str] = None,
    db: Optional[DatabaseManager] = None,
) -> Optional[Request]:

    return await get_repository(db).complete(
        request_id,
        result_id=result_id,
    )


async def fail_request(
    request_id: int,
    error: str,
    *,
    db: Optional[DatabaseManager] = None,
) -> Optional[Request]:

    return await get_repository(db).fail(
        request_id,
        error,
    )


async def cancel_request(
    request_id: int,
    reason: Optional[str] = None,
    *,
    db: Optional[DatabaseManager] = None,
) -> Optional[Request]:

    return await get_repository(db).cancel(
        request_id,
        reason,
    )


async def request_statistics(
    *,
    db: Optional[DatabaseManager] = None,
) -> dict[str, int]:

    return await get_repository(db).statistics(
        db=db
    )


__all__ = [
    "RequestRepository",
    "get_repository",
    "create_request",
    "get_request",
    "start_request",
    "complete_request",
    "fail_request",
    "cancel_request",
    "request_statistics",
]