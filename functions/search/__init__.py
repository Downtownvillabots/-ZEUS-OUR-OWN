"""
Search feature entrypoint module.
"""

from __future__ import annotations

from app.runtime import Runtime
from functions.search.handlers.query import setup_search_handlers
from functions.search.request.handlers import setup_request_handlers


def register(runtime: Runtime) -> None:
    db_manager = getattr(runtime, "db_manager", None)
    if db_manager:
        setup_search_handlers(runtime.client, db_manager)
        setup_request_handlers(runtime.client, db_manager)
