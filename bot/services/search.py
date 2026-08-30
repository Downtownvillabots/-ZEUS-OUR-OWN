"""
bot/services/search.py

Search service for the bot.

Responsibilities:
    - Normalize search queries.
    - Build MongoDB search queries.
    - Search indexed Telegram files.
    - Rank results.
    - Paginate results.
    - Keep database/search logic away from Telegram handlers.

Expected database document shape:

{
    "_id": ObjectId(...),
    "file_name": "Avatar 2009 1080p.mkv",
    "file_id": "...",
    "file_size": 123456789,
    "file_type": "video",
    "caption": "...",
    "created_at": datetime(...)
}

The service is deliberately tolerant of slightly different schemas because
the old bot/database may contain documents with different field names.
"""

import logging
import math
import re
from typing import Any, Optional

from bot.database import db

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50

MAX_QUERY_LENGTH = 256
MIN_QUERY_LENGTH = 1

# Search fields used by the indexed-file collection.
SEARCH_FIELDS = (
    "file_name",
    "filename",
    "name",
    "caption",
)

# Fields used when returning documents.
PROJECTION = {
    "_id": 1,
    "file_name": 1,
    "filename": 1,
    "name": 1,
    "file_id": 1,
    "telegram_file_id": 1,
    "file_size": 1,
    "size": 1,
    "file_type": 1,
    "media_type": 1,
    "caption": 1,
    "chat_id": 1,
    "message_id": 1,
    "created_at": 1,
}


# ============================================================================
# Query normalization
# ============================================================================

def normalize_search_query(query: str) -> str:
    """
    Normalize a user search query.

    The old bot removed things such as:
        - languages
        - seasons
        - quality tags

    We preserve the useful architecture but avoid destroying too much of
    the user's original query.

    Example:

        "Avatar 2009 1080p English"
        ->
        "Avatar 2009"

    """
    if query is None:
        return ""

    query = str(query).strip()

    if not query:
        return ""

    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH]

    query = re.sub(r"\s+", " ", query)

    # Remove URLs.
    query = re.sub(
        r"https?://\S+",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    # Common quality tags.
    query = re.sub(
        r"\b(?:360p|480p|576p|720p|1080p|1440p|2160p|4320p|"
        r"4k|8k|uhd|fhd|hd)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    # Common language tags.
    query = re.sub(
        r"\b(?:hindi|hin|english|eng|malayalam|mal|tamil|tam|"
        r"telugu|tel|kannada|kan|bengali|ben|marathi|mar|urdu|"
        r"gujarati|guj|punjabi|pun)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    # Common source / codec tags.
    query = re.sub(
        r"\b(?:webrip|web[-_. ]dl|bluray|blu[-_. ]ray|brrip|"
        r"hdrip|hdtv|dvdrip|dvdscr|camrip|cam|pre[-_. ]dvd|"
        r"x264|x265|h264|h265|hevc|av1|aac|ddp|dd5\.1|"
        r"atmos)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )

    # Normalize season notation.
    query = re.sub(
        r"\bseason\s*0*(\d+)\b",
        r"S\1",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"\bs0*(\d+)\b",
        r"S\1",
        query,
        flags=re.IGNORECASE,
    )

    query = re.sub(
        r"\s+",
        " ",
        query,
    ).strip()

    return query


def normalize_filename(filename: str) -> str:
    """
    Normalize a filename for comparison/ranking.
    """
    if not filename:
        return ""

    filename = str(filename).lower()

    # Remove extension.
    filename = re.sub(
        r"\.(?:mkv|mp4|avi|mov|wmv|flv|webm|m4v|"
        r"mp3|m4a|flac|wav|aac|ogg|pdf|zip|rar|7z)$",
        "",
        filename,
        flags=re.IGNORECASE,
    )

    # Convert separators to spaces.
    filename = re.sub(
        r"[_\-.]+",
        " ",
        filename,
    )

    # Remove common metadata.
    filename = re.sub(
        r"\b(?:360p|480p|576p|720p|1080p|1440p|2160p|"
        r"4k|8k|web[- ]?dl|web[- ]?rip|bluray|"
        r"brrip|hdrip|hdtv|x264|x265|h264|h265|hevc)\b",
        " ",
        filename,
        flags=re.IGNORECASE,
    )

    filename = re.sub(
        r"\s+",
        " ",
        filename,
    ).strip()

    return filename


def tokenize_query(query: str) -> list[str]:
    """
    Convert a query into useful search tokens.
    """
    if not query:
        return []

    tokens = re.findall(
        r"[a-zA-Z0-9]+",
        query.lower(),
    )

    # Remove extremely small noise tokens except season markers.
    result = []

    for token in tokens:
        if len(token) == 1 and not token.isdigit():
            continue

        result.append(token)

    return result


# ============================================================================
# MongoDB query builders
# ============================================================================

def build_regex_query(
    query: str,
) -> dict:
    """
    Build a case-insensitive regex search across filename fields.

    Regex escaping is mandatory because the query is user-controlled.
    """
    escaped = re.escape(query)

    return {
        "$or": [
            {
                field: {
                    "$regex": escaped,
                    "$options": "i",
                }
            }
            for field in SEARCH_FIELDS
        ]
    }


def build_token_query(
    query: str,
) -> dict:
    """
    Build a token-based MongoDB search.

    Every token must be present somewhere across the searchable fields.
    """
    tokens = tokenize_query(query)

    if not tokens:
        return build_regex_query(query)

    conditions = []

    for token in tokens:
        escaped = re.escape(token)

        conditions.append(
            {
                "$or": [
                    {
                        field: {
                            "$regex": escaped,
                            "$options": "i",
                        }
                    }
                    for field in SEARCH_FIELDS
                ]
            }
        )

    return {
        "$and": conditions
    }


def build_search_queries(
    query: str,
) -> list[dict]:
    """
    Generate search strategies in priority order.

    1. Exact phrase.
    2. All tokens.
    3. Individual tokens.

    This allows the service to remain useful even when filenames contain
    extra release metadata.
    """
    queries = []

    if query:
        queries.append(
            build_regex_query(query)
        )

    token_query = build_token_query(query)

    if token_query not in queries:
        queries.append(token_query)

    tokens = tokenize_query(query)

    for token in tokens:
        query_data = build_regex_query(token)

        if query_data not in queries:
            queries.append(query_data)

    return queries


# ============================================================================
# Document helpers
# ============================================================================

def extract_filename(
    document: dict,
) -> str:
    """
    Extract filename from different supported schemas.
    """
    return (
        document.get("file_name")
        or document.get("filename")
        or document.get("name")
        or ""
    )


def extract_file_id(
    document: dict,
) -> Optional[str]:
    """
    Extract Telegram file ID.
    """
    value = (
        document.get("file_id")
        or document.get("telegram_file_id")
    )

    if value is None:
        return None

    return str(value)


def extract_file_size(
    document: dict,
) -> Optional[int]:
    """
    Extract file size.
    """
    value = (
        document.get("file_size")
        or document.get("size")
    )

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ============================================================================
# Ranking
# ============================================================================

def calculate_text_score(
    filename: str,
    query: str,
) -> float:
    """
    Calculate a lightweight relevance score.

    Scoring:

        100 = exact normalized match
         90 = query appears as complete phrase
         75 = query appears in filename
         60 = all query tokens are present
         lower = partial token matches

    This is intentionally inexpensive because ranking can happen after
    MongoDB has already reduced the candidate set.
    """
    filename_normalized = normalize_filename(
        filename
    )

    query_normalized = normalize_filename(
        query
    )

    if not filename_normalized or not query_normalized:
        return 0.0

    if filename_normalized == query_normalized:
        return 100.0

    if query_normalized in filename_normalized:
        return 90.0

    query_tokens = tokenize_query(
        query_normalized
    )

    if not query_tokens:
        return 0.0

    filename_tokens = set(
        tokenize_query(filename_normalized)
    )

    matched = sum(
        1
        for token in query_tokens
        if token in filename_tokens
    )

    if matched == len(query_tokens):
        return 75.0

    if matched > 0:
        return (
            30.0
            * matched
            / len(query_tokens)
        )

    return 0.0


def rank_documents(
    documents: list[dict],
    query: str,
) -> list[dict]:
    """
    Rank candidate documents by filename relevance.
    """
    scored = []

    for document in documents:
        filename = extract_filename(
            document
        )

        score = calculate_text_score(
            filename,
            query,
        )

        scored.append(
            (
                score,
                document,
            )
        )

    scored.sort(
        key=lambda item: (
            item[0],
            len(extract_filename(item[1])),
        ),
        reverse=True,
    )

    return [
        document
        for _, document in scored
    ]


# ============================================================================
# Database access
# ============================================================================

def get_file_collection():
    """
    Resolve the indexed-file MongoDB collection.

    Different versions of the old bot used different collection names.
    """
    candidates = (
        "files",
        "file",
        "media",
        "movies",
        "filename",
        "col",
    )

    for name in candidates:
        collection = getattr(
            db,
            name,
            None,
        )

        if collection is not None:
            return collection

    raise RuntimeError(
        "No indexed-file collection is configured in bot.database.db"
    )


async def count_search_results(
    collection,
    mongo_query: dict,
) -> int:
    """
    Count documents matching the query.
    """
    try:
        return await collection.count_documents(
            mongo_query
        )
    except Exception:
        logger.exception(
            "Failed counting search results"
        )
        return 0


async def fetch_search_candidates(
    collection,
    mongo_query: dict,
    limit: int,
) -> list[dict]:
    """
    Fetch a bounded candidate set.

    We intentionally do not load an entire collection into memory.
    """
    cursor = (
        collection
        .find(
            mongo_query,
            PROJECTION,
        )
        .sort(
            [
                ("file_name", 1),
                ("_id", 1),
            ]
        )
        .limit(limit)
    )

    try:
        return await cursor.to_list(
            length=limit
        )
    except TypeError:
        # Compatibility with some Motor/PyMongo combinations.
        return await cursor.to_list(
            limit
        )


# ============================================================================
# Main search
# ============================================================================

async def search_files(
    query: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    """
    Search indexed files.

    Returns:

    {
        "files": [...],
        "total": int,
        "page": int,
        "page_size": int,
        "total_pages": int,
        "query": str,
    }
    """
    query = normalize_search_query(
        query
    )

    if not query:
        return {
            "files": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 1,
            "query": "",
        }

    page = max(
        1,
        int(page or 1),
    )

    page_size = max(
        1,
        min(
            int(page_size or DEFAULT_PAGE_SIZE),
            MAX_PAGE_SIZE,
        ),
    )

    collection = get_file_collection()

    queries = build_search_queries(
        query
    )

    # ------------------------------------------------------------------------
    # First pass: exact phrase.
    # ------------------------------------------------------------------------

    primary_query = queries[0]

    total = await count_search_results(
        collection,
        primary_query,
    )

    selected_query = primary_query

    # ------------------------------------------------------------------------
    # Fallback: token search.
    # ------------------------------------------------------------------------

    if total == 0 and len(queries) > 1:
        token_query = queries[1]

        token_total = await count_search_results(
            collection,
            token_query,
        )

        if token_total > 0:
            total = token_total
            selected_query = token_query

    # ------------------------------------------------------------------------
    # No result.
    # ------------------------------------------------------------------------

    if total == 0:
        return {
            "files": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 1,
            "query": query,
        }

    total_pages = max(
        1,
        math.ceil(
            total / page_size
        ),
    )

    # Prevent impossible page requests.
    if page > total_pages:
        page = total_pages

    skip = (
        page - 1
    ) * page_size

    # ------------------------------------------------------------------------
    # Candidate retrieval.
    #
    # Fetch extra candidates so local ranking does not only rank the exact
    # page returned by MongoDB.
    # ------------------------------------------------------------------------

    candidate_limit = min(
        max(
            page_size * 5,
            50,
        ),
        500,
    )

    candidates = await fetch_search_candidates(
        collection,
        selected_query,
        candidate_limit,
    )

    candidates = rank_documents(
        candidates,
        query,
    )

    # ------------------------------------------------------------------------
    # Page extraction.
    # ------------------------------------------------------------------------

    page_files = candidates[
        skip:skip + page_size
    ]

    # If the candidate window cannot cover the requested page, use MongoDB
    # pagination directly as a fallback.
    if page > 1 and not page_files:
        cursor = (
            collection
            .find(
                selected_query,
                PROJECTION,
            )
            .sort(
                [
                    ("file_name", 1),
                    ("_id", 1),
                ]
            )
            .skip(skip)
            .limit(page_size)
        )

        page_files = await cursor.to_list(
            length=page_size
        )

    return {
        "files": page_files,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "query": query,
    }


# ============================================================================
# Alternative broad search
# ============================================================================

async def search_files_broad(
    query: str,
    limit: int = 50,
) -> list[dict]:
    """
    Broad search useful for:
        - spell checking
        - suggestions
        - admin tools
        - autocomplete

    It returns a bounded result set.
    """
    query = normalize_search_query(
        query
    )

    if not query:
        return []

    limit = max(
        1,
        min(
            int(limit),
            500,
        ),
    )

    collection = get_file_collection()

    mongo_query = build_token_query(
        query
    )

    documents = await fetch_search_candidates(
        collection,
        mongo_query,
        limit,
    )

    return rank_documents(
        documents,
        query,
    )


# ============================================================================
# Search suggestions
# ============================================================================

def similarity_score(
    value: str,
    query: str,
) -> float:
    """
    Simple token similarity without an external dependency.

    This function can later be replaced with RapidFuzz because RapidFuzz
    is already part of the project dependencies.
    """
    from difflib import SequenceMatcher

    if not value or not query:
        return 0.0

    return SequenceMatcher(
        None,
        normalize_filename(value),
        normalize_filename(query),
    ).ratio()


async def get_search_suggestions(
    query: str,
    limit: int = 5,
) -> list[str]:
    """
    Generate filename suggestions.

    Used by the spell-check feature inherited from the old bot.
    """
    query = normalize_search_query(
        query
    )

    if not query:
        return []

    limit = max(
        1,
        min(
            int(limit),
            20,
        ),
    )

    documents = await search_files_broad(
        query,
        limit=100,
    )

    suggestions = []

    seen = set()

    for document in documents:
        filename = extract_filename(
            document
        )

        if not filename:
            continue

        normalized = normalize_filename(
            filename
        )

        if normalized in seen:
            continue

        score = similarity_score(
            filename,
            query,
        )

        if score >= 0.35:
            suggestions.append(
                (
                    score,
                    filename,
                )
            )

            seen.add(normalized)

    suggestions.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return [
        filename
        for _, filename in suggestions[:limit]
    ]


# ============================================================================
# Search by exact filename
# ============================================================================

async def search_exact_filename(
    filename: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search for an exact filename.
    """
    filename = str(
        filename or ""
    ).strip()

    if not filename:
        return []

    limit = max(
        1,
        min(
            int(limit),
            100,
        ),
    )

    collection = get_file_collection()

    conditions = []

    for field in SEARCH_FIELDS:
        conditions.append(
            {
                field: {
                    "$regex": (
                        "^"
                        + re.escape(filename)
                        + "$"
                    ),
                    "$options": "i",
                }
            }
        )

    mongo_query = {
        "$or": conditions
    }

    cursor = (
        collection
        .find(
            mongo_query,
            PROJECTION,
        )
        .limit(limit)
    )

    return await cursor.to_list(
        length=limit
    )


# ============================================================================
# Search statistics
# ============================================================================

async def get_search_count(
    query: str,
) -> int:
    """
    Return the number of matching files.
    """
    query = normalize_search_query(
        query
    )

    if not query:
        return 0

    collection = get_file_collection()

    mongo_query = build_token_query(
        query
    )

    return await count_search_results(
        collection,
        mongo_query,
    )


# ============================================================================
# Search validation
# ============================================================================

def validate_search_query(
    query: str,
) -> tuple[bool, str]:
    """
    Validate a search query before execution.

    Returns:
        (is_valid, normalized_query)
    """
    if query is None:
        return False, ""

    query = str(query).strip()

    if len(query) < MIN_QUERY_LENGTH:
        return False, ""

    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH]

    normalized = normalize_search_query(
        query
    )

    if not normalized:
        return False, ""

    return True, normalized


# ============================================================================
# Search service object
# ============================================================================

class SearchService:
    """
    Object-oriented wrapper around the search service.

    Keeping this class available makes it easy to inject a different
    database/search backend later.
    """

    def __init__(
        self,
        database=None,
    ):
        self.database = (
            database
            if database is not None
            else db
        )

    async def search(
        self,
        query: str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        return await search_files(
            query=query,
            page=page,
            page_size=page_size,
        )

    async def suggestions(
        self,
        query: str,
        limit: int = 5,
    ) -> list[str]:
        return await get_search_suggestions(
            query=query,
            limit=limit,
        )

    async def exact(
        self,
        filename: str,
        limit: int = 20,
    ) -> list[dict]:
        return await search_exact_filename(
            filename=filename,
            limit=limit,
        )

    async def count(
        self,
        query: str,
    ) -> int:
        return await get_search_count(
            query=query,
        )


search_service = SearchService()


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "SearchService",
    "search_service",
    "search_files",
    "search_files_broad",
    "search_exact_filename",
    "get_search_suggestions",
    "get_search_count",
    "normalize_search_query",
    "normalize_filename",
    "tokenize_query",
    "validate_search_query",
]