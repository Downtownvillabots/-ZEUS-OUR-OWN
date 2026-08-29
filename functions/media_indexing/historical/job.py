"""Cancellable historical indexing jobs."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from ..models import IndexMode, IndexStats


@dataclass(slots=True)
class HistoricalJob:
    chat_id: int
    start_message_id: int
    mode: IndexMode
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    stats: IndexStats = field(default_factory=IndexStats)

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()
