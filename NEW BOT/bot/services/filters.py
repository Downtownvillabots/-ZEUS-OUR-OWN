"""
bot/services/filters.py

Search and filename filtering utilities for the new bot.

This module is intentionally independent from Pyrogram and MongoDB.
It converts human Telegram searches and indexed filenames into structured
metadata that the search engine can use consistently.

Supported:
- year
- season
- episode
- language
- video quality
- source/release type
- codec
- audio channels
- HDR / Dolby Vision
- web/bluray/HDTV/cam sources
- resolution
- common subtitle/audio markers
- filename cleanup
- tokenization
- filter matching
- filter extraction from user queries
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LANGUAGE_ALIASES: dict[str, str] = {
    "hin": "hindi",
    "hindi": "hindi",
    "eng": "english",
    "english": "english",
    "en": "english",
    "mal": "malayalam",
    "malayalam": "malayalam",
    "ml": "malayalam",
    "tam": "tamil",
    "tamil": "tamil",
    "ta": "tamil",
    "tel": "telugu",
    "telugu": "telugu",
    "te": "telugu",
    "kan": "kannada",
    "kannada": "kannada",
    "kn": "kannada",
    "ben": "bengali",
    "bengali": "bengali",
    "bn": "bengali",
    "mar": "marathi",
    "marathi": "marathi",
    "mr": "marathi",
    "urd": "urdu",
    "urdu": "urdu",
    "guj": "gujarati",
    "gujarati": "gujarati",
    "gu": "gujarati",
    "pun": "punjabi",
    "punjabi": "punjabi",
    "pa": "punjabi",
    "asm": "assamese",
    "assamese": "assamese",
    "ori": "odia",
    "odia": "odia",
    "nep": "nepali",
    "nepali": "nepali",
    "ara": "arabic",
    "arabic": "arabic",
    "fra": "french",
    "french": "french",
    "spa": "spanish",
    "spanish": "spanish",
    "ger": "german",
    "german": "german",
    "ita": "italian",
    "italian": "italian",
    "kor": "korean",
    "korean": "korean",
    "jap": "japanese",
    "japanese": "japanese",
    "chi": "chinese",
    "chinese": "chinese",
    "mandarin": "chinese",
    "rus": "russian",
    "russian": "russian",
    "por": "portuguese",
    "portuguese": "portuguese",
    "ind": "indonesian",
    "indonesian": "indonesian",
    "thai": "thai",
    "tur": "turkish",
    "turkish": "turkish",
}

LANGUAGE_CODES = {
    "english": "en",
    "hindi": "hi",
    "malayalam": "ml",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "bengali": "bn",
    "marathi": "mr",
    "urdu": "ur",
    "gujarati": "gu",
    "punjabi": "pa",
    "assamese": "as",
    "odia": "or",
    "nepali": "ne",
    "arabic": "ar",
    "french": "fr",
    "spanish": "es",
    "german": "de",
    "italian": "it",
    "korean": "ko",
    "japanese": "ja",
    "chinese": "zh",
    "russian": "ru",
    "portuguese": "pt",
    "indonesian": "id",
    "thai": "th",
    "turkish": "tr",
}

QUALITY_ALIASES: dict[str, str] = {
    "240p": "240p",
    "360p": "360p",
    "480p": "480p",
    "576p": "576p",
    "720p": "720p",
    "720": "720p",
    "1080p": "1080p",
    "1080": "1080p",
    "fhd": "1080p",
    "1440p": "1440p",
    "1440": "1440p",
    "2k": "1440p",
    "2160p": "2160p",
    "2160": "2160p",
    "4k": "2160p",
    "uhd": "2160p",
    "4320p": "4320p",
    "8k": "4320p",
}

SOURCE_ALIASES: dict[str, str] = {
    "webdl": "web-dl",
    "web-dl": "web-dl",
    "webdlrip": "web-dl",
    "web-dlrip": "web-dl",
    "webrip": "web-rip",
    "web-rip": "web-rip",
    "web": "web-rip",
    "bluray": "blu-ray",
    "blu-ray": "blu-ray",
    "brrip": "blu-ray",
    "br-rip": "blu-ray",
    "bdrip": "blu-ray",
    "bd-rip": "blu-ray",
    "dvdrip": "dvd-rip",
    "dvd-rip": "dvd-rip",
    "hdtv": "hdtv",
    "hdrip": "hd-rip",
    "hd-rip": "hd-rip",
    "cam": "cam",
    "camrip": "cam",
    "cam-rip": "cam",
    "ts": "telesync",
    "telesync": "telesync",
    "hdcam": "hd-cam",
    "tc": "telecine",
    "telecine": "telecine",
    "scr": "screener",
    "screener": "screener",
}

CODEC_ALIASES: dict[str, str] = {
    "x264": "x264",
    "h264": "x264",
    "avc": "x264",
    "x265": "x265",
    "h265": "x265",
    "hevc": "x265",
    "av1": "av1",
    "vp9": "vp9",
    "mpeg2": "mpeg2",
    "xvid": "xvid",
}

AUDIO_ALIASES: dict[str, str] = {
    "aac": "aac",
    "ac3": "ac3",
    "dd": "ac3",
    "dd5.1": "ac3",
    "eac3": "eac3",
    "ddp": "eac3",
    "ddp5.1": "eac3",
    "dts": "dts",
    "dtshd": "dts-hd",
    "dts-hd": "dts-hd",
    "truehd": "truehd",
    "atmos": "atmos",
    "opus": "opus",
    "mp3": "mp3",
    "flac": "flac",
}

SOURCE_PATTERN = re.compile(
    r"(?<![a-z0-9])("
    r"web[\s._-]?dl|web[\s._-]?dlrip|web[\s._-]?rip|"
    r"blu[\s._-]?ray|b[dr][\s._-]?rip|"
    r"dvd[\s._-]?rip|hd[\s._-]?rip|hdtv|"
    r"hd[\s._-]?cam|cam[\s._-]?rip|cam|"
    r"telesync|telecine|screener|scr"
    r")(?![a-z0-9])",
    re.IGNORECASE,
)

QUALITY_PATTERN = re.compile(
    r"(?<![a-z0-9])("
    r"4320p|2160p|1440p|1080p|720p|576p|480p|360p|240p|"
    r"8k|4k|2k|uhd|fhd"
    r")(?![a-z0-9])",
    re.IGNORECASE,
)

YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

SEASON_PATTERNS = (
    re.compile(r"(?<![a-z0-9])s(\d{1,3})(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])season[\s._-]*(\d{1,3})(?![a-z0-9])", re.I),
)

EPISODE_PATTERNS = (
    re.compile(r"(?<![a-z0-9])e(\d{1,4})(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])ep[\s._-]*(\d{1,4})(?![a-z0-9])", re.I),
    re.compile(r"(?<![a-z0-9])episode[\s._-]*(\d{1,4})(?![a-z0-9])", re.I),
)

SEASON_EPISODE_PATTERN = re.compile(
    r"(?<![a-z0-9])s(\d{1,3})[\s._-]*e(\d{1,4})(?![a-z0-9])",
    re.I,
)

RESOLUTION_PATTERN = re.compile(
    r"(?<![a-z0-9])(\d{3,4})x(\d{3,4})(?![a-z0-9])",
    re.I,
)

AUDIO_CHANNEL_PATTERN = re.compile(
    r"(?<![a-z0-9])(\d(?:\.\d){1,2})(?![a-z0-9])"
)

BITRATE_PATTERN = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(kbps|mbps)(?![a-z0-9])",
    re.I,
)

FPS_PATTERN = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(?:fps|hz)(?![a-z0-9])",
    re.I,
)

VOLUME_PATTERN = re.compile(
    r"(?<![a-z0-9])vol(?:ume)?[\s._-]*(\d+)(?![a-z0-9])",
    re.I,
)

PART_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:part|pt)[\s._-]*(\d{1,3})(?![a-z0-9])",
    re.I,
)

DISC_PATTERN = re.compile(
    r"(?<![a-z0-9])disc[\s._-]*(\d{1,3})(?![a-z0-9])",
    re.I,
)

YEAR_RANGE_PATTERN = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[\s._-]*(?:-|to)[\s._-]*((?:19|20)\d{2})(?!\d)",
    re.I,
)

HDR_PATTERN = re.compile(
    r"(?<![a-z0-9])(hdr10\+?|hdr|hlg)(?![a-z0-9])",
    re.I,
)

DOLBY_VISION_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:dv|dolby[\s._-]?vision)(?![a-z0-9])",
    re.I,
)

THREE_D_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:3d|sbs|hsbs|tab|htab)(?![a-z0-9])",
    re.I,
)

SUBTITLE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:sub|subs|subtitle|subtitles|"
    r"multi[\s._-]?sub|multi[\s._-]?subs)(?![a-z0-9])",
    re.I,
)

DUAL_AUDIO_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:dual[\s._-]?audio|dual[\s._-]?aud|"
    r"multi[\s._-]?audio|multiaudio)(?![a-z0-9])",
    re.I,
)

PROPER_AUDIO_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:original[\s._-]?audio|org[\s._-]?audio)(?![a-z0-9])",
    re.I,
)

IMAX_PATTERN = re.compile(
    r"(?<![a-z0-9])imax(?![a-z0-9])",
    re.I,
)

EXTENSION_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:mkv|mp4|avi|mov|m4v|webm|flv|ts|m2ts)(?![a-z0-9])",
    re.I,
)

SPECIAL_MARKER_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:proper|repack|remux|internal|limited|extended|uncut|"
    r"directors[\s._-]?cut|director'?s[\s._-]?cut|"
    r"complete|complete[\s._-]?series|collection|pack|batch)(?![a-z0-9])",
    re.I,
)

COMMON_TAG_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"nf|netflix|amzn|amazon|prime|hotstar|disney|"
    r"sony|zee5|voot|aha|jiocinema|hbo|max|"
    r"apple|appletv|paramount|peacock|"
    r"yts|yify|rarbg|eztv|ettv|"
    r"org|repack|proper|sample"
    r")(?![a-z0-9])",
    re.I,
)

# Terms that are usually technical metadata and should not form part of a
# movie title after extraction.
NOISE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"dual[\s._-]?audio|multi[\s._-]?audio|"
    r"multi[\s._-]?sub(?:title)?s?|"
    r"original[\s._-]?audio|"
    r"proper|repack|remux|internal|limited|extended|uncut|"
    r"complete(?:[\s._-]?series)?|collection|batch|pack|"
    r"nf|netflix|amzn|amazon|prime|hotstar|disney|sony|zee5|voot|"
    r"yts|yify|rarbg|eztv|ettv|sample"
    r")(?![a-z0-9])",
    re.I,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class MediaFilters:
    year: Optional[int] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_from: Optional[int] = None
    episode_to: Optional[int] = None

    languages: list[str] = field(default_factory=list)
    quality: Optional[str] = None
    qualities: list[str] = field(default_factory=list)

    source: Optional[str] = None
    sources: list[str] = field(default_factory=list)

    codec: Optional[str] = None
    audio: Optional[str] = None
    audio_channels: Optional[str] = None

    hdr: Optional[str] = None
    dolby_vision: bool = False
    three_d: bool = False
    dual_audio: bool = False
    subtitles: bool = False
    imax: bool = False

    resolution_width: Optional[int] = None
    resolution_height: Optional[int] = None

    extension: Optional[str] = None
    part: Optional[int] = None
    disc: Optional[int] = None
    volume: Optional[int] = None

    bitrate_value: Optional[float] = None
    bitrate_unit: Optional[str] = None
    fps: Optional[float] = None

    special_markers: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def language(self) -> Optional[str]:
        return self.languages[0] if self.languages else None


@dataclass(slots=True)
class ParsedFilename:
    original: str
    title: str
    filters: MediaFilters
    tokens: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "title": self.title,
            "filters": self.filters.as_dict(),
            "tokens": list(self.tokens),
        }


@dataclass(slots=True)
class FilteredText:
    text: str
    removed: list[str]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def normalize_unicode(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return value.replace("\u2013", "-").replace("\u2014", "-")


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_separators(value: str) -> str:
    """
    Convert filename separators to spaces while retaining apostrophes and
    ampersands where they may be meaningful in titles.
    """
    value = normalize_unicode(value)
    value = value.replace("_", " ")
    value = value.replace(".", " ")
    value = re.sub(r"[\[\]{}<>]", " ", value)
    value = re.sub(r"\s*-\s*", " ", value)
    value = normalize_spaces(value)
    return value


def canonical_language(value: str) -> Optional[str]:
    key = normalize_spaces(value).lower()
    return LANGUAGE_ALIASES.get(key)


def canonical_quality(value: str) -> Optional[str]:
    key = normalize_spaces(value).lower()
    return QUALITY_ALIASES.get(key)


def canonical_source(value: str) -> Optional[str]:
    key = normalize_spaces(value).lower()
    key = key.replace("_", "-").replace(" ", "")
    return SOURCE_ALIASES.get(key)


def canonical_codec(value: str) -> Optional[str]:
    key = normalize_spaces(value).lower().replace("-", "")
    return CODEC_ALIASES.get(key)


def canonical_audio(value: str) -> Optional[str]:
    key = normalize_spaces(value).lower()
    return AUDIO_ALIASES.get(key)


def dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in items:
        if not item:
            continue
        item = str(item).strip()
        if not item:
            continue

        marker = item.lower()
        if marker in seen:
            continue

        seen.add(marker)
        result.append(item)

    return result


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------

def extract_years(text: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    range_match = YEAR_RANGE_PATTERN.search(text or "")
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return None, start, end

    years = [int(x) for x in YEAR_PATTERN.findall(text or "")]
    if not years:
        return None, None, None

    return years[-1], None, None


def extract_season_episode(
    text: str,
) -> tuple[
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[int],
]:
    season = None
    episode = None

    se = SEASON_EPISODE_PATTERN.search(text or "")
    if se:
        season = int(se.group(1))
        episode = int(se.group(2))
        return season, episode, None, None

    for pattern in SEASON_PATTERNS:
        match = pattern.search(text or "")
        if match:
            season = int(match.group(1))
            break

    for pattern in EPISODE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            episode = int(match.group(1))
            break

    return season, episode, None, None


def extract_languages(text: str) -> list[str]:
    normalized = normalize_separators(text).lower()
    found: list[str] = []

    # Long names first to avoid accidental partial matches.
    for alias in sorted(LANGUAGE_ALIASES, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            canonical = LANGUAGE_ALIASES[alias]
            if canonical not in found:
                found.append(canonical)

    return found


def extract_quality(text: str) -> tuple[Optional[str], list[str]]:
    found: list[str] = []

    for match in QUALITY_PATTERN.finditer(text or ""):
        canonical = canonical_quality(match.group(1))
        if canonical and canonical not in found:
            found.append(canonical)

    return (found[0] if found else None), found


def extract_sources(text: str) -> tuple[Optional[str], list[str]]:
    found: list[str] = []

    for match in SOURCE_PATTERN.finditer(text or ""):
        raw = match.group(1)
        normalized = (
            raw.lower()
            .replace(".", "")
            .replace("_", "")
            .replace(" ", "")
        )
        canonical = canonical_source(normalized)
        if canonical and canonical not in found:
            found.append(canonical)

    return (found[0] if found else None), found


def extract_codec(text: str) -> Optional[str]:
    normalized = normalize_separators(text).lower()

    for alias in sorted(CODEC_ALIASES, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            return CODEC_ALIASES[alias]

    return None


def extract_audio(text: str) -> Optional[str]:
    normalized = normalize_separators(text).lower()

    for alias in sorted(AUDIO_ALIASES, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            return AUDIO_ALIASES[alias]

    return None


def extract_audio_channels(text: str) -> Optional[str]:
    for match in AUDIO_CHANNEL_PATTERN.finditer(text or ""):
        value = match.group(1)

        # 2.0 / 5.1 / 7.1 are meaningful; avoid treating years or random
        # decimal values as audio layouts.
        if value in {"1.0", "2.0", "2.1", "5.1", "6.1", "7.1", "7.2"}:
            return value

    return None


def extract_resolution(text: str) -> tuple[Optional[int], Optional[int]]:
    match = RESOLUTION_PATTERN.search(text or "")
    if not match:
        return None, None

    return int(match.group(1)), int(match.group(2))


def extract_hdr(text: str) -> Optional[str]:
    match = HDR_PATTERN.search(text or "")
    if not match:
        return None
    return match.group(1).lower()


def extract_bitrate(text: str) -> tuple[Optional[float], Optional[str]]:
    match = BITRATE_PATTERN.search(text or "")
    if not match:
        return None, None

    return float(match.group(1)), match.group(2).lower()


def extract_fps(text: str) -> Optional[float]:
    match = FPS_PATTERN.search(text or "")
    if not match:
        return None

    return float(match.group(1))


def extract_extension(text: str) -> Optional[str]:
    match = EXTENSION_PATTERN.search(text or "")
    return match.group(0).lower() if match else None


def extract_special_markers(text: str) -> list[str]:
    normalized = normalize_separators(text).lower()

    markers = [
        "proper",
        "repack",
        "remux",
        "internal",
        "limited",
        "extended",
        "uncut",
        "director's cut",
        "complete",
        "collection",
        "pack",
        "batch",
    ]

    return [
        marker
        for marker in markers
        if re.search(
            rf"(?<![a-z0-9]){re.escape(marker).replace(' ', r'[\s._-]+')}"
            r"(?![a-z0-9])",
            normalized,
            re.I,
        )
    ]


def extract_tags(text: str) -> list[str]:
    normalized = normalize_separators(text).lower()

    aliases = [
        "nf",
        "netflix",
        "amzn",
        "amazon",
        "prime",
        "hotstar",
        "disney",
        "sony",
        "zee5",
        "voot",
        "aha",
        "jiocinema",
        "hbo",
        "max",
        "apple",
        "appletv",
        "paramount",
        "peacock",
        "yts",
        "yify",
        "rarbg",
        "eztv",
        "ettv",
    ]

    result = []
    for tag in aliases:
        if re.search(rf"(?<![a-z0-9]){re.escape(tag)}(?![a-z0-9])", normalized):
            result.append(tag)

    return result


# ---------------------------------------------------------------------------
# Filter extraction
# ---------------------------------------------------------------------------

def extract_filters(text: str) -> MediaFilters:
    text = normalize_unicode(str(text or ""))

    year, year_from, year_to = extract_years(text)
    season, episode, episode_from, episode_to = extract_season_episode(text)

    quality, qualities = extract_quality(text)
    source, sources = extract_sources(text)

    width, height = extract_resolution(text)

    return MediaFilters(
        year=year,
        year_from=year_from,
        year_to=year_to,
        season=season,
        episode=episode,
        episode_from=episode_from,
        episode_to=episode_to,
        languages=extract_languages(text),
        quality=quality,
        qualities=qualities,
        source=source,
        sources=sources,
        codec=extract_codec(text),
        audio=extract_audio(text),
        audio_channels=extract_audio_channels(text),
        hdr=extract_hdr(text),
        dolby_vision=bool(DOLBY_VISION_PATTERN.search(text)),
        three_d=bool(THREE_D_PATTERN.search(text)),
        dual_audio=bool(DUAL_AUDIO_PATTERN.search(text)),
        subtitles=bool(SUBTITLE_PATTERN.search(text)),
        imax=bool(IMAX_PATTERN.search(text)),
        resolution_width=width,
        resolution_height=height,
        extension=extract_extension(text),
        part=_extract_int(PART_PATTERN, text),
        disc=_extract_int(DISC_PATTERN, text),
        volume=_extract_int(VOLUME_PATTERN, text),
        bitrate_value=extract_bitrate(text)[0],
        bitrate_unit=extract_bitrate(text)[1],
        fps=extract_fps(text),
        special_markers=extract_special_markers(text),
        tags=extract_tags(text),
    )


def _extract_int(pattern: re.Pattern[str], text: str) -> Optional[int]:
    match = pattern.search(text or "")
    return int(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def remove_filter_terms(text: str, filters: Optional[MediaFilters] = None) -> FilteredText:
    """
    Remove technical metadata from a search string.

    This is useful for:
        "Breaking Bad S02 1080p Hindi WEB-DL"
    becoming:
        "Breaking Bad"
    """
    value = normalize_unicode(str(text or ""))
    removed: list[str] = []

    patterns: list[re.Pattern[str]] = [
        YEAR_RANGE_PATTERN,
        YEAR_PATTERN,
        SEASON_EPISODE_PATTERN,
        *SEASON_PATTERNS,
        *EPISODE_PATTERNS,
        QUALITY_PATTERN,
        SOURCE_PATTERN,
        CODEC_PATTERN if "CODEC_PATTERN" in globals() else re.compile(
            r"(?<![a-z0-9])(?:x264|x265|h264|h265|hevc|avc|av1|vp9|xvid)(?![a-z0-9])",
            re.I,
        ),
        AUDIO_PATTERN if "AUDIO_PATTERN" in globals() else re.compile(
            r"(?<![a-z0-9])(?:aac|ac3|ddp?|eac3|dts(?:-hd)?|truehd|atmos|opus|mp3|flac)(?![a-z0-9])",
            re.I,
        ),
        HDR_PATTERN,
        DOLBY_VISION_PATTERN,
        THREE_D_PATTERN,
        DUAL_AUDIO_PATTERN,
        SUBTITLE_PATTERN,
        IMAX_PATTERN,
        EXTENSION_PATTERN,
        SPECIAL_MARKER_PATTERN,
        COMMON_TAG_PATTERN,
        RESOLUTION_PATTERN,
        BITRATE_PATTERN,
        FPS_PATTERN,
        VOLUME_PATTERN,
        PART_PATTERN,
        DISC_PATTERN,
    ]

    # Language terms need a dynamic pattern because the list is configurable.
    language_pattern = re.compile(
        r"(?<![a-z0-9])(?:"
        + "|".join(
            re.escape(x)
            for x in sorted(LANGUAGE_ALIASES, key=len, reverse=True)
        )
        + r")(?![a-z0-9])",
        re.I,
    )
    patterns.append(language_pattern)

    for pattern in patterns:
        matches = list(pattern.finditer(value))
        if matches:
            removed.extend(match.group(0) for match in matches)
            value = pattern.sub(" ", value)

    value = cleanup_title_text(value)

    return FilteredText(
        text=value,
        removed=dedupe(removed),
    )


def cleanup_title_text(text: str) -> str:
    value = normalize_unicode(text)

    # Remove common surrounding separators after metadata removal.
    value = re.sub(r"[\[\]{}()<>]", " ", value)
    value = re.sub(r"[|]+", " ", value)
    value = re.sub(r"[/\\]+", " ", value)

    # A hyphen is useful inside titles only when surrounded by letters/numbers.
    # Treat repeated separators as whitespace.
    value = re.sub(r"[_]+", " ", value)
    value = re.sub(r"\.{2,}", " ", value)
    value = re.sub(r"\s*[-]{2,}\s*", " ", value)

    value = normalize_spaces(value)

    # Remove leading/trailing punctuation that remains after tag removal.
    value = re.sub(r"^[\s._\-,:;]+", "", value)
    value = re.sub(r"[\s._\-,:;]+$", "", value)

    return normalize_spaces(value)


def clean_filename(
    filename: str,
    *,
    bad_words: Optional[Iterable[str]] = None,
) -> str:
    """
    Clean a filename for display/search while retaining meaningful title text.

    Unlike the old implementation this does not blindly remove every word
    beginning with '[' or '@'; it first removes technical media metadata.
    """
    value = str(filename or "")

    filtered = remove_filter_terms(value)
    value = filtered.text

    if bad_words:
        unwanted = {str(x).strip().lower() for x in bad_words if str(x).strip()}
        words = [
            word
            for word in value.split()
            if word.lower() not in unwanted
        ]
        value = " ".join(words)

    return cleanup_title_text(value)


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def tokenize(text: str) -> tuple[str, ...]:
    value = normalize_separators(text).lower()

    # Keep alphanumeric title tokens.
    value = re.sub(r"[^a-z0-9\u0080-\uffff]+", " ", value)

    tokens = []
    for token in value.split():
        if len(token) <= 1:
            continue
        tokens.append(token)

    return tuple(dedupe(tokens))


def normalized_title(text: str) -> str:
    return " ".join(tokenize(text))


def compact_title(text: str) -> str:
    return "".join(tokenize(text))


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

def parse_filename(filename: str) -> ParsedFilename:
    original = str(filename or "")
    filters = extract_filters(original)
    title = remove_filter_terms(original, filters).text
    tokens = tokenize(title)

    return ParsedFilename(
        original=original,
        title=title,
        filters=filters,
        tokens=tokens,
    )


def parse_search_query(query: str) -> ParsedFilename:
    """
    Parse a user query using the same rules as indexed filenames.

    Example:
        parse_search_query("Avengers 2019 1080p Hindi S01")
    """
    return parse_filename(query)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def matches_year(filters: MediaFilters, target: MediaFilters) -> bool:
    if target.year is not None:
        return filters.year == target.year

    if target.year_from is not None and filters.year is not None:
        if filters.year < target.year_from:
            return False

    if target.year_to is not None and filters.year is not None:
        if filters.year > target.year_to:
            return False

    return True


def matches_season(filters: MediaFilters, target: MediaFilters) -> bool:
    if target.season is None:
        return True

    return filters.season == target.season


def matches_episode(filters: MediaFilters, target: MediaFilters) -> bool:
    if target.episode is None:
        return True

    return filters.episode == target.episode


def matches_language(filters: MediaFilters, target: MediaFilters) -> bool:
    if not target.languages:
        return True

    if not filters.languages:
        return False

    requested = set(target.languages)
    available = set(filters.languages)

    return bool(requested & available)


def matches_quality(filters: MediaFilters, target: MediaFilters) -> bool:
    if not target.qualities:
        return True

    if not filters.qualities:
        return False

    return bool(set(target.qualities) & set(filters.qualities))


def matches_source(filters: MediaFilters, target: MediaFilters) -> bool:
    if not target.sources:
        return True

    if not filters.sources:
        return False

    return bool(set(target.sources) & set(filters.sources))


def matches_codec(filters: MediaFilters, target: MediaFilters) -> bool:
    if not target.codec:
        return True

    return filters.codec == target.codec


def matches_audio(filters: MediaFilters, target: MediaFilters) -> bool:
    if not target.audio:
        return True

    return filters.audio == target.audio


def matches_boolean_filters(
    filters: MediaFilters,
    target: MediaFilters,
) -> bool:
    if target.dolby_vision and not filters.dolby_vision:
        return False

    if target.three_d and not filters.three_d:
        return False

    if target.dual_audio and not filters.dual_audio:
        return False

    if target.subtitles and not filters.subtitles:
        return False

    if target.imax and not filters.imax:
        return False

    return True


def matches_media_filters(
    filename_or_filters: str | MediaFilters,
    requested: str | MediaFilters,
) -> bool:
    actual = (
        extract_filters(filename_or_filters)
        if isinstance(filename_or_filters, str)
        else filename_or_filters
    )

    target = (
        extract_filters(requested)
        if isinstance(requested, str)
        else requested
    )

    return all(
        (
            matches_year(actual, target),
            matches_season(actual, target),
            matches_episode(actual, target),
            matches_language(actual, target),
            matches_quality(actual, target),
            matches_source(actual, target),
            matches_codec(actual, target),
            matches_audio(actual, target),
            matches_boolean_filters(actual, target),
        )
    )


# ---------------------------------------------------------------------------
# Filter scoring
# ---------------------------------------------------------------------------

def filter_match_score(
    filename_or_filters: str | MediaFilters,
    requested: str | MediaFilters,
) -> float:
    """
    Returns a 0-100 metadata compatibility score.

    This is intentionally separate from title similarity. The search engine
    can combine title_score + filter_match_score.
    """
    actual = (
        extract_filters(filename_or_filters)
        if isinstance(filename_or_filters, str)
        else filename_or_filters
    )

    target = (
        extract_filters(requested)
        if isinstance(requested, str)
        else requested
    )

    checks: list[tuple[bool, bool, float]] = []

    if target.year is not None:
        checks.append((True, actual.year == target.year, 20.0))

    if target.season is not None:
        checks.append((True, actual.season == target.season, 20.0))

    if target.episode is not None:
        checks.append((True, actual.episode == target.episode, 10.0))

    if target.languages:
        checks.append(
            (
                True,
                bool(set(target.languages) & set(actual.languages)),
                15.0,
            )
        )

    if target.qualities:
        checks.append(
            (
                True,
                bool(set(target.qualities) & set(actual.qualities)),
                15.0,
            )
        )

    if target.sources:
        checks.append(
            (
                True,
                bool(set(target.sources) & set(actual.sources)),
                10.0,
            )
        )

    if target.codec:
        checks.append((True, actual.codec == target.codec, 5.0))

    if target.audio:
        checks.append((True, actual.audio == target.audio, 5.0))

    if target.dolby_vision:
        checks.append((True, actual.dolby_vision, 5.0))

    if target.hdr:
        checks.append((True, actual.hdr == target.hdr, 5.0))

    if target.dual_audio:
        checks.append((True, actual.dual_audio, 5.0))

    if target.subtitles:
        checks.append((True, actual.subtitles, 5.0))

    if target.imax:
        checks.append((True, actual.imax, 5.0))

    if not checks:
        return 100.0

    total_weight = sum(weight for present, _, weight in checks if present)
    matched_weight = sum(
        weight
        for present, matched, weight in checks
        if present and matched
    )

    return round((matched_weight / total_weight) * 100.0, 2)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def query_title(query: str) -> str:
    return remove_filter_terms(query).text


def query_languages(query: str) -> list[str]:
    return extract_filters(query).languages


def query_quality(query: str) -> Optional[str]:
    return extract_filters(query).quality


def query_year(query: str) -> Optional[int]:
    return extract_filters(query).year


def query_season(query: str) -> Optional[int]:
    return extract_filters(query).season


def query_episode(query: str) -> Optional[int]:
    return extract_filters(query).episode


def is_filter_only_query(query: str) -> bool:
    parsed = parse_search_query(query)
    return not bool(parsed.tokens)


def build_search_variants(
    query: str,
    *,
    include_season: bool = True,
) -> list[str]:
    """
    Generate conservative variants useful for databases that contain
    inconsistent filename conventions.
    """
    parsed = parse_search_query(query)
    title = parsed.title

    if not title:
        return []

    variants = [title]

    if parsed.filters.year:
        variants.append(f"{title} {parsed.filters.year}")

    if include_season and parsed.filters.season is not None:
        s = parsed.filters.season
        variants.extend(
            [
                f"{title} S{s:02d}",
                f"{title} S{s}",
                f"{title} Season {s}",
            ]
        )

    return dedupe(variants)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def filters_to_text(filters: MediaFilters) -> str:
    parts: list[str] = []

    if filters.year:
        parts.append(str(filters.year))

    if filters.year_from or filters.year_to:
        start = filters.year_from or ""
        end = filters.year_to or ""
        parts.append(f"{start}-{end}")

    if filters.season is not None:
        parts.append(f"S{filters.season:02d}")

    if filters.episode is not None:
        parts.append(f"E{filters.episode:02d}")

    if filters.languages:
        parts.extend(filters.languages)

    if filters.quality:
        parts.append(filters.quality)

    if filters.source:
        parts.append(filters.source)

    if filters.codec:
        parts.append(filters.codec)

    if filters.audio:
        parts.append(filters.audio)

    if filters.audio_channels:
        parts.append(filters.audio_channels)

    if filters.hdr:
        parts.append(filters.hdr)

    if filters.dolby_vision:
        parts.append("Dolby Vision")

    if filters.dual_audio:
        parts.append("Dual Audio")

    if filters.subtitles:
        parts.append("Subtitles")

    if filters.three_d:
        parts.append("3D")

    if filters.imax:
        parts.append("IMAX")

    if filters.resolution_width and filters.resolution_height:
        parts.append(
            f"{filters.resolution_width}x{filters.resolution_height}"
        )

    return " ".join(parts)


def display_title(filename: str) -> str:
    parsed = parse_filename(filename)
    return parsed.title or str(filename or "").strip()


# ---------------------------------------------------------------------------
# Compatibility aliases from the old bot
# ---------------------------------------------------------------------------

def clean_search_text(search_raw: str) -> str:
    return query_title(search_raw).title()


def generate_season_variations(
    search_raw: str,
    season_number: int,
) -> list[str]:
    return [
        f"{search_raw} s{season_number:02d}",
        f"{search_raw} season {season_number}",
        f"{search_raw} season {season_number:02d}",
    ]


# ---------------------------------------------------------------------------
# Exported API
# ---------------------------------------------------------------------------

__all__ = [
    "MediaFilters",
    "ParsedFilename",
    "FilteredText",
    "extract_filters",
    "extract_years",
    "extract_season_episode",
    "extract_languages",
    "extract_quality",
    "extract_sources",
    "extract_codec",
    "extract_audio",
    "extract_audio_channels",
    "extract_resolution",
    "extract_hdr",
    "extract_bitrate",
    "extract_fps",
    "extract_extension",
    "extract_special_markers",
    "extract_tags",
    "remove_filter_terms",
    "cleanup_title_text",
    "clean_filename",
    "tokenize",
    "normalized_title",
    "compact_title",
    "parse_filename",
    "parse_search_query",
    "matches_media_filters",
    "filter_match_score",
    "query_title",
    "query_languages",
    "query_quality",
    "query_year",
    "query_season",
    "query_episode",
    "is_filter_only_query",
    "build_search_variants",
    "filters_to_text",
    "display_title",
    "clean_search_text",
    "generate_season_variations",
]
