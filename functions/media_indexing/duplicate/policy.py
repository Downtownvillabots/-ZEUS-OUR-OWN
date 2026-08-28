"""Duplicate policy: fast candidate filtering plus exact metadata comparison."""
from __future__ import annotations
from ..models import ParsedMedia


def same_record(media: ParsedMedia, candidate: dict, file_size: int, file_unique_id: str | None) -> bool:
    # Telegram identity is the strongest available signal.
    existing_id = candidate.get("file_unique_id")
    if file_unique_id and existing_id and file_unique_id == existing_id:
        return True

    # User requirement: size is a major duplicate signal. It is deliberately
    # combined with title/metadata so unrelated 200 MB files do not collide.
    if int(candidate.get("file_size", -1)) != int(file_size):
        return False
    if candidate.get("normalized_title") != media.normalized_title:
        return False
    if candidate.get("year") not in (None, media.year) and media.year is not None:
        return False
    if candidate.get("season") != media.season or candidate.get("episode") != media.episode:
        return False
    if candidate.get("resolution") and media.resolution and candidate["resolution"] != media.resolution:
        return False
    if candidate.get("quality") and media.quality and candidate["quality"] != media.quality:
        return False
    return True
