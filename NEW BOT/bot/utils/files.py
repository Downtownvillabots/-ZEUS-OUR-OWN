"""
File utility helpers.

These functions only manipulate metadata/paths.
They do not perform Telegram uploads or downloads.
"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Optional

from .formatting import format_bytes
from .text import safe_filename_text


def get_extension(
    filename: Optional[str],
) -> str:

    if not filename:
        return ""

    suffix = Path(
        str(filename)
    ).suffix

    return suffix.lower().lstrip(".")


def get_filename(
    filename: Optional[str],
) -> str:

    if not filename:
        return ""

    return Path(
        str(filename)
    ).name


def get_mime_type(
    filename: Optional[str],
) -> Optional[str]:

    if not filename:
        return None

    mime, _ = mimetypes.guess_type(
        str(filename)
    )

    return mime


def is_video(
    filename: Optional[str],
) -> bool:

    mime = get_mime_type(
        filename
    )

    if mime:
        return mime.startswith(
            "video/"
        )

    return get_extension(
        filename
    ) in {
        "mp4",
        "mkv",
        "avi",
        "mov",
        "webm",
        "m4v",
    }


def is_audio(
    filename: Optional[str],
) -> bool:

    mime = get_mime_type(
        filename
    )

    if mime:
        return mime.startswith(
            "audio/"
        )

    return get_extension(
        filename
    ) in {
        "mp3",
        "m4a",
        "aac",
        "flac",
        "wav",
        "ogg",
        "opus",
    }


def is_image(
    filename: Optional[str],
) -> bool:

    mime = get_mime_type(
        filename
    )

    if mime:
        return mime.startswith(
            "image/"
        )

    return get_extension(
        filename
    ) in {
        "jpg",
        "jpeg",
        "png",
        "webp",
        "gif",
        "bmp",
    }


def is_archive(
    filename: Optional[str],
) -> bool:

    return get_extension(
        filename
    ) in {
        "zip",
        "rar",
        "7z",
        "tar",
        "gz",
        "bz2",
        "xz",
    }


def sanitize_filename(
    filename: Optional[str],
    *,
    maximum: int = 255,
) -> str:

    return safe_filename_text(
        filename,
        maximum=maximum,
    )


def split_filename(
    filename: Optional[str],
) -> tuple[str, str]:

    if not filename:
        return (
            "",
            "",
        )

    path = Path(
        str(filename)
    )

    return (
        path.stem,
        path.suffix,
    )


def ensure_directory(
    path: str | Path,
) -> Path:

    directory = Path(
        path
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory


def safe_join(
    base: str | Path,
    filename: str,
) -> Path:

    base_path = Path(
        base
    ).resolve()

    clean_name = sanitize_filename(
        filename
    )

    target = (
        base_path
        / clean_name
    ).resolve()

    if (
        target != base_path
        and base_path not in target.parents
    ):

        raise ValueError(
            "Path escapes the base directory."
        )

    return target


def human_file_info(
    filename: str,
    size: Optional[int] = None,
) -> str:

    name = sanitize_filename(
        filename
    )

    if size is None:
        return name

    return (
        f"{name} • "
        f"{format_bytes(size)}"
    )


__all__ = [
    "get_extension",
    "get_filename",
    "get_mime_type",
    "is_video",
    "is_audio",
    "is_image",
    "is_archive",
    "sanitize_filename",
    "split_filename",
    "ensure_directory",
    "safe_join",
    "human_file_info",
]