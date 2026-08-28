"""Conservative movie/series metadata parser."""
from __future__ import annotations
import re
from .patterns import YEAR, RESOLUTION, FOUR_K, CODEC, QUALITY, SERIES, LANGUAGES
from .normalizer import strip_noise, normalize_title


def _first(pattern, text):
    m = pattern.search(text)
    return m.group(1) if m else None


def parse(filename: str, caption: str | None = None):
    source = strip_noise(filename)
    year_text = _first(YEAR, source)
    year = int(year_text) if year_text else None
    resolution = _first(RESOLUTION, source)
    if not resolution and FOUR_K.search(source):
        resolution = "2160p"
    quality = _first(QUALITY, source)
    codec = _first(CODEC, source)
    series_match = None
    for pattern in SERIES:
        series_match = pattern.search(source)
        if series_match:
            break
    season = int(series_match.group("season")) if series_match else None
    episode = int(series_match.group("episode")) if series_match else None
    languages = []
    for token in re.findall(r"[A-Za-z]+", source.casefold()):
        lang = LANGUAGES.get(token)
        if lang and lang not in languages:
            languages.append(lang)
    title = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", source)
    for pattern in (YEAR, RESOLUTION, QUALITY, CODEC):
        title = pattern.sub(" ", title)
    title = FOUR_K.sub(" ", title)
    for pattern in SERIES:
        title = pattern.sub(" ", title)
    for token in LANGUAGES:
        title = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", title, flags=re.I)
    title = re.sub(r"[._-]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip() or "Unknown"
    from ..models import ParsedMedia
    return ParsedMedia(
        original_name=filename, title=title, normalized_title=normalize_title(title),
        year=year, resolution=resolution.lower() if resolution else None,
        quality=quality.upper() if quality else None, codec=codec.upper() if codec else None,
        languages=tuple(languages), season=season, episode=episode,
        is_series=series_match is not None,
    )
