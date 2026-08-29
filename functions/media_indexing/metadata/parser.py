"""
Metadata Extraction Engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ExtractedMetadata:
    original_name: str
    clean_name: str
    title: str
    normalized_title: str
    year: int | None
    resolution: str | None
    quality: str | None
    codec: str | None
    languages: list[str]
    season: int | None
    episode: int | None
    is_series: bool


class MetadataParser:
    LANG_MAP = {
        "MAL": "Malayalam", "MALAYALAM": "Malayalam",
        "KAN": "Kannada", "KANNADA": "Kannada",
        "TEL": "Telugu", "TELUGU": "Telugu",
        "TAM": "Tamil", "TAMIL": "Tamil",
        "ENG": "English", "ENGLISH": "English",
        "HIN": "Hindi", "HINDI": "Hindi",
        "BEN": "Bengali", "MAR": "Marathi", "GUJ": "Gujarati"
    }

    RESOLUTIONS = ["2160P", "4K", "1440P", "1080P", "720P", "576P", "480P", "360P", "240P", "144P"]
    QUALITIES = ["WEB-DL", "WEBRIP", "BLURAY", "BDRIP", "HDRIP", "DVDRIP", "CAM", "HDTV", "REMUX", "HDTC"]
    CODECS = ["HEVC", "H265", "H264", "X265", "X264", "AV1", "AVC"]

    @classmethod
    def clean_noise(cls, text: str) -> str:
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        text = re.sub(r"@[A-Za-z0-9_]+", "", text)
        text = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", text)
        text = re.sub(r"[\._\-\+]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def parse(cls, filename: str, caption: str = "") -> ExtractedMetadata:
        raw_text = f"{filename} {caption}".strip()
        cleaned = cls.clean_noise(raw_text)

        season = episode = None
        is_series = False

        se_match = re.search(r"\bS(\d{1,2})\s*E(\d{1,4})\b", raw_text, re.IGNORECASE)
        if not se_match:
            se_match = re.search(r"\bSeason\s*(\d{1,2})\s*Episode\s*(\d{1,4})\b", raw_text, re.IGNORECASE)

        if se_match:
            season = int(se_match.group(1))
            episode = int(se_match.group(2))
            is_series = True

        year = None
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", raw_text)
        if year_match:
            year = int(year_match.group(1))

        res_found = next((r.upper() for r in cls.RESOLUTIONS if re.search(r"\b" + r + r"\b", raw_text, re.IGNORECASE)), None)
        q_found = next((q.upper() for q in cls.QUALITIES if re.search(r"\b" + q + r"\b", raw_text, re.IGNORECASE)), None)
        c_found = next((c.upper() for c in cls.CODECS if re.search(r"\b" + c + r"\b", raw_text, re.IGNORECASE)), None)

        langs = {full_lang for token, full_lang in cls.LANG_MAP.items() if re.search(r"\b" + token + r"\b", raw_text, re.IGNORECASE)}

        title_tokens = []
        for token in cleaned.split():
            t_upper = token.upper()
            if (year and token == str(year)) or t_upper in cls.RESOLUTIONS or t_upper in cls.QUALITIES or t_upper in cls.CODECS or t_upper in cls.LANG_MAP:
                break
            title_tokens.append(token)

        title = " ".join(title_tokens).strip() or cleaned
        return ExtractedMetadata(
            original_name=filename, clean_name=cleaned, title=title, normalized_title=title.lower(),
            year=year, resolution=res_found, quality=q_found, codec=c_found, languages=list(langs),
            season=season, episode=episode, is_series=is_series
        )
