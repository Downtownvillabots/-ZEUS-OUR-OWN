"""
Media Indexing Module Entrypoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from functions.media_indexing.feature import register_media_indexing

if TYPE_CHECKING:
    from app.runtime import Runtime


def register(runtime: Runtime) -> None:
    register_media_indexing(runtime)
