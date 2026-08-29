"""
MongoDB Request Collection Repository.
"""

from typing import Any, Optional
from functions.search.request.models import MovieRequest, RequestStatus


class RequestRepository:
    def __init__(self, db_manager: Any) -> None:
        self.db_manager = db_manager
        self.collection = self.db_manager.primary_db["movie_requests"]

    async def get_next_request_id(self) -> str:
        counter_col = self.db_manager.primary_db["counters"]
        result = await counter_col.find_one_and_update(
            {"_id": "request_id"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=True,
        )
        seq = result.get("seq", 1)
        return f"REQ-{seq:06d}"

    async def create_request(self, request: MovieRequest) -> None:
        await self.collection.insert_one(request.to_dict())

    async def get_request_by_id(self, request_id: str) -> Optional[dict]:
        return await self.collection.find_one({"request_id": request_id})

    async def mark_fulfilled(self, request_id: str) -> bool:
        res = await self.collection.update_one(
            {"request_id": request_id, "status": RequestStatus.PENDING.value},
            {"$set": {"status": RequestStatus.FULFILLED.value, "notification_sent": True}},
        )
        return res.modified_count > 0
