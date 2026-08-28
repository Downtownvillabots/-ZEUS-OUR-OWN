"""Layered duplicate policy.

Telegram identity is strongest. Exact normalized title + size + structural
metadata is the fallback. Size alone is never treated as a global identity.
"""
from __future__ import annotations
from ..models import ParsedMedia


def is_duplicate(
    media: ParsedMedia,
    candidate: dict,
    *,
    file_size: int,
    file_unique_id: str | None,
) -> bool:
    existing_unique_id = candidate.get("file_unique_id")
    if file_unique_id and existing_unique_id and file_unique_id == existing_unique_id:
        return True

    if int(candidate.get("file_size", -1)) != int(file_size):
        return False
    if candidate.get("normalized_title") != media.normalized_title:
        return False

    existing_year = candidate.get("year")
    if existing_year is not None and media.year is not None and int(existing_year) != int(media.year):
        return False

    if candidate.get("season") != media.season or candidate.get("episode") != media.episode:
        return False

    if candidate.get("resolution") and media.resolution:
        if candidate["resolution"] != media.resolution:
            return False

    if candidate.get("quality") and media.quality:
        if candidate["quality"] != media.quality:
            return False

    if candidate.get("languages") and media.languages:
        if tuple(candidate["languages"]) != tuple(media.languages):
            return False

    return True
