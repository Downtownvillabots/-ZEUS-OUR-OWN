"""
Isolated User Search Session Management.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from functions.search.config import SEARCH_SESSION_TIMEOUT_SECONDS


@dataclass
class SearchSession:
    user_id: int
    query: str
    selected_title: str | None = None
    selected_year: int | None = None
    selected_language: str | None = None
    selected_resolution: str | None = None
    selected_quality: str | None = None
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.last_activity) > SEARCH_SESSION_TIMEOUT_SECONDS

    def touch(self) -> None:
        self.last_activity = time.time()


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, SearchSession] = {}

    def create_session(self, user_id: int, query: str) -> SearchSession:
        session = SearchSession(user_id=user_id, query=query)
        self._sessions[user_id] = session
        return session

    def get_session(self, user_id: int) -> SearchSession | None:
        session = self._sessions.get(user_id)
        if not session:
            return None
        if session.is_expired():
            self.clear_session(user_id)
            return None
        session.touch()
        return session

    def clear_session(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)


SESSION_MANAGER = SessionManager()
