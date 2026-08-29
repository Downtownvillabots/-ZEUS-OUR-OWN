"""
Movie Request Data Models and Status Enum.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class MovieRequest:
    request_id: str
    user_id: int
    username: Optional[str]
    display_name: str
    original_query: str
    normalized_query: str
    title: str
    year: Optional[int] = None
    language: Optional[str] = None
    imdb_id: Optional[str] = None
    imdb_title: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: RequestStatus = RequestStatus.PENDING
    request_channel_id: Optional[int] = None
    request_message_id: Optional[int] = None
    notification_sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "original_query": self.original_query,
            "normalized_query": self.normalized_query,
            "title": self.title,
            "year": self.year,
            "language": self.language,
            "imdb_id": self.imdb_id,
            "imdb_title": self.imdb_title,
            "created_at": self.created_at,
            "status": self.status.value,
            "request_channel_id": self.request_channel_id,
            "request_message_id": self.request_message_id,
            "notification_sent": self.notification_sent,
        }
