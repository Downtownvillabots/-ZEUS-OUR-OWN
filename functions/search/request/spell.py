"""
Lightweight Query Normalization and Fuzzy Spell Suggestion Engine.
"""

import re
from difflib import SequenceMatcher
from typing import Optional


def normalize_title_query(raw_text: str) -> tuple[str, Optional[int], Optional[str]]:
    text = raw_text.strip()
    
    year_match = re.search(r"\b(19\d\d|20\d\d)\b", text)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        text = text.replace(year_match.group(0), " ")

    languages = ["tamil", "malayalam", "telugu", "hindi", "english", "kannada"]
    found_lang = None
    for lang in languages:
        if re.search(rf"\b{lang}\b", text, re.IGNORECASE):
            found_lang = lang.lower()
            text = re.sub(rf"\b{lang}\b", " ", text, flags=re.IGNORECASE)
            break

    text = re.sub(r"@\w+|https?://\S+|www\.\S+|[\[\]\(\)\{\}\._\-+]", " ", text)
    cleaned_title = " ".join(text.split())

    return cleaned_title, year, found_lang


def find_fuzzy_suggestion(query_title: str, candidate_titles: list[str], cutoff: float = 0.75) -> Optional[str]:
    query_title = query_title.lower()
    best_match = None
    best_score = 0.0

    for candidate in candidate_titles:
        score = SequenceMatcher(None, query_title, candidate.lower()).ratio()
        if score > best_score and score >= cutoff:
            best_score = score
            best_match = candidate

    return best_match
