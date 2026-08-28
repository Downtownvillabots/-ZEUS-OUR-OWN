"""Filename/caption normalization shared by indexing and future search."""
from __future__ import annotations
import re
import unicodedata

USERNAME = re.compile(r"(?<!\w)@[A-Za-z0-9_]{2,64}")
URL = re.compile(r"https?://\S+", re.I)


def strip_noise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = URL.sub(" ", text)
    text = USERNAME.sub(" ", text)
    text = text.replace("_", " ")
    text = re.sub(r"[|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(text: str) -> str:
    text = strip_noise(text).casefold()
    text = re.sub(r"[.,:;()[\]{}]+", " ", text)
    text = re.sub(r"[-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
