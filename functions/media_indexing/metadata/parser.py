"""Conservative filename metadata parser."""
from __future__ import annotations
import re
from .normalizer import clean_text, normalize_title
from .patterns import YEAR, RESOLUTION, FOUR_K, CODEC, QUALITY, SERIES, LANGUAGES
from ..models import ParsedMedia


def _first(pattern, text):
    match = pattern.search(text)
    return match.group(1) if match else None


def _series(text):
    for pattern in SERIES:
        match = pattern.search(text)
        if match:
            return int(match.group("season")), int(match.group("episode"))
    return None


def _languages(text):
    result = []
    for token in re.findall(r"[A-Za-z]+", text.casefold()):
        value = LANGUAGES.get(token)
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _title(text):
    text = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", text)
    for pattern in (YEAR, RESOLUTION, QUALITY, CODEC):
        text = pattern.sub(" ", text)
    text = FOUR_K.sub(" ", text)
    for pattern in SERIES:
        text = pattern.sub(" ", text)
    for token in LANGUAGES:
        text = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", text, flags=re.I)
    text = re.sub(r"[._-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip() or "Unknown"


def parse(filename: str, caption: str | None = None) -> ParsedMedia:
    source = clean_text(filename)
    title = _title(source)
    series = _series(source)
    resolution = _first(RESOLUTION, source)
    if not resolution and FOUR_K.search(source):
        resolution = "2160p"
    quality = _first(QUALITY, source)
    codec = _first(CODEC, source)
    year_text = _first(YEAR, source)
    return ParsedMedia(
        original_name=filename,
        clean_name=clean_text(filename),
        title=title,
        normalized_title=normalize_title(title),
        year=int(year_text) if year_text else None,
        resolution=resolution.lower() if resolution else None,
        quality=quality.upper() if quality else None,
        codec=codec.upper() if codec else None,
        languages=_languages(source),
        audio_languages=(),
        subtitle_languages=(),
        season=series[0] if series else None,
        episode=series[1] if series else None,
        is_series=series is not None,
    )
