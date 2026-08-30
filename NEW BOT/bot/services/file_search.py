"""
bot/services/file_search.py

File search service for the new bot.

Responsibilities
----------------
- Search stored Telegram files
- Normalize search queries
- Apply filters
- Rank results
- Pagination
- Result counting
- File lookup
- Safe result formatting

Architecture
------------

Telegram Handler
       |
       v
 FileSearchService
       |
       +---- FileRepository / Database
       |
       +---- Query Normalizer
       |
       +---- Result Ranking
       |
       v
  Search Results
       |
       v
  Delivery Service
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Iterable,
    Optional,
)

from rapidfuzz.fuzz import ratio

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

MIN_QUERY_LENGTH = 2

DEFAULT_SCORE_THRESHOLD = 45

# Common release/file keywords which should not dominate matching.
NOISE_WORDS = {
    "movie",
    "movies",
    "film",
    "films",
    "download",
    "watch",
    "full",
    "hd",
    "web",
    "rip",
    "print",
    "file",
    "files",
}

QUALITY_VALUES = {
    "360p",
    "480p",
    "576p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4k",
    "8k",
}

LANGUAGE_ALIASES = {
    "hin": "hindi",
    "hindi": "hindi",

    "eng": "english",
    "english": "english",

    "tam": "tamil",
    "tamil": "tamil",

    "tel": "telugu",
    "telugu": "telugu",

    "mal": "malayalam",
    "malayalam": "malayalam",

    "kan": "kannada",
    "kannada": "kannada",

    "ben": "bengali",
    "bengali": "bengali",

    "mar": "marathi",
    "marathi": "marathi",

    "guj": "gujarati",
    "gujarati": "gujarati",

    "pun": "punjabi",
    "punjabi": "punjabi",

    "urd": "urdu",
    "urdu": "urdu",
}


# ============================================================================
# Data models
# ============================================================================

@dataclass(slots=True)
class SearchFilters:
    """
    Optional filters extracted from a user query.
    """

    year: Optional[int] = None
    quality: Optional[str] = None
    language: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None

    raw_query: str = ""

    clean_query: str = ""


@dataclass(slots=True)
class SearchResult:
    """
    One normalized file search result.
    """

    file_id: Any
    file_name: str

    file_size: Optional[int] = None

    score: float = 0.0

    chat_id: Optional[int] = None

    message_id: Optional[int] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(slots=True)
class SearchPage:
    """
    Paginated search response.
    """

    query: str

    page: int

    page_size: int

    total: int

    results: list[SearchResult]

    has_previous: bool

    has_next: bool

    total_pages: int


# ============================================================================
# Query normalizer
# ============================================================================

class QueryNormalizer:
    """
    Cleans user search queries while preserving useful information.
    """

    YEAR_RE = re.compile(
        r"\b(19\d{2}|20\d{2})\b"
    )

    QUALITY_RE = re.compile(
        r"\b(360p|480p|576p|720p|1080p|1440p|2160p|4k|8k)\b",
        re.IGNORECASE,
    )

    SEASON_RE = re.compile(
        r"\bs(?:eason)?\s*0*(\d{1,2})\b",
        re.IGNORECASE,
    )

    EPISODE_RE = re.compile(
        r"\be(?:pisode)?\s*0*(\d{1,4})\b",
        re.IGNORECASE,
    )

    @classmethod
    def normalize_spaces(
        cls,
        value: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    @classmethod
    def normalize_text(
        cls,
        value: str,
    ) -> str:
        value = value.lower()

        value = value.replace(
            "_",
            " ",
        )

        value = value.replace(
            ".",
            " ",
        )

        value = value.replace(
            "-",
            " ",
        )

        value = cls.normalize_spaces(
            value
        )

        return value

    @classmethod
    def extract(
        cls,
        query: str,
    ) -> SearchFilters:

        raw = str(
            query or ""
        ).strip()

        normalized = cls.normalize_text(
            raw
        )

        year = None
        quality = None
        language = None
        season = None
        episode = None

        year_match = cls.YEAR_RE.search(
            normalized
        )

        if year_match:
            try:
                year = int(
                    year_match.group(1)
                )
            except ValueError:
                year = None

        quality_match = cls.QUALITY_RE.search(
            normalized
        )

        if quality_match:
            quality = (
                quality_match.group(1)
                .lower()
            )

        season_match = cls.SEASON_RE.search(
            normalized
        )

        if season_match:
            try:
                season = int(
                    season_match.group(1)
                )
            except ValueError:
                season = None

        episode_match = cls.EPISODE_RE.search(
            normalized
        )

        if episode_match:
            try:
                episode = int(
                    episode_match.group(1)
                )
            except ValueError:
                episode = None

        words = normalized.split()

        language_words = []

        for word in words:
            canonical = LANGUAGE_ALIASES.get(
                word
            )

            if canonical:
                language_words.append(
                    canonical
                )

        if language_words:
            language = language_words[0]

        # Remove technical search tokens.
        cleaned = cls.YEAR_RE.sub(
            " ",
            normalized,
        )

        cleaned = cls.QUALITY_RE.sub(
            " ",
            cleaned,
        )

        cleaned = cls.SEASON_RE.sub(
            " ",
            cleaned,
        )

        cleaned = cls.EPISODE_RE.sub(
            " ",
            cleaned,
        )

        for alias in LANGUAGE_ALIASES:
            cleaned = re.sub(
                rf"\b{re.escape(alias)}\b",
                " ",
                cleaned,
            )

        cleaned = cls.normalize_spaces(
            cleaned
        )

        return SearchFilters(
            year=year,
            quality=quality,
            language=language,
            season=season,
            episode=episode,
            raw_query=raw,
            clean_query=cleaned,
        )


# ============================================================================
# Ranking
# ============================================================================

class ResultRanker:
    """
    Scores database results against a search query.
    """

    @staticmethod
    def normalize_filename(
        filename: str,
    ) -> str:
        value = str(
            filename or ""
        ).lower()

        value = re.sub(
            r"[\[\]\(\)\{\}_\-.]+",
            " ",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()

    @classmethod
    def remove_noise(
        cls,
        text: str,
    ) -> str:

        words = cls.normalize_filename(
            text
        ).split()

        cleaned = [
            word
            for word in words
            if word not in NOISE_WORDS
        ]

        return " ".join(
            cleaned
        )

    @classmethod
    def score(
        cls,
        query: str,
        filename: str,
    ) -> float:

        query_normalized = cls.remove_noise(
            query
        )

        filename_normalized = cls.remove_noise(
            filename
        )

        if not query_normalized:
            return 0.0

        if not filename_normalized:
            return 0.0

        # Exact normalized match.
        if query_normalized == filename_normalized:
            return 100.0

        # Exact phrase containment.
        if query_normalized in filename_normalized:
            return 95.0

        # Filename beginning with search.
        if filename_normalized.startswith(
            query_normalized
        ):
            return 90.0

        fuzzy = ratio(
            query_normalized,
            filename_normalized,
        )

        # Word-level bonus.
        query_words = set(
            query_normalized.split()
        )

        filename_words = set(
            filename_normalized.split()
        )

        if query_words:
            overlap = (
                len(
                    query_words
                    & filename_words
                )
                / len(query_words)
            )

            fuzzy = (
                fuzzy * 0.75
                + overlap * 25
            )

        return round(
            fuzzy,
            2,
        )


# ============================================================================
# Repository adapter
# ============================================================================

class FileRepository:
    """
    Database adapter.

    This class intentionally keeps MongoDB implementation details outside
    the search service.

    The database layer can later implement these methods directly.
    """

    def __init__(
        self,
        db=None,
    ):
        self.db = db

    def set_database(
        self,
        db,
    ):
        self.db = db

    async def search(
        self,
        query: str,
        filters: Optional[SearchFilters] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        if self.db is None:
            raise RuntimeError(
                "FileRepository database is not configured"
            )

        # Support several database implementations.
        if hasattr(
            self.db,
            "search_files",
        ):
            result = await self.db.search_files(
                query=query,
                filters=filters,
                limit=limit,
            )

            if result is None:
                return []

            if isinstance(
                result,
                list,
            ):
                return result

            return [
                item
                async for item in result
            ]

        # Support a direct files collection.
        collection = getattr(
            self.db,
            "files",
            None,
        )

        if collection is None:
            collection = getattr(
                self.db,
                "file_col",
                None,
            )

        if collection is None:
            raise RuntimeError(
                "Database does not expose a file search interface"
            )

        mongo_query: dict[str, Any] = {}

        # Text search is preferred if the collection has a text index.
        if query:
            mongo_query["$text"] = {
                "$search": query
            }

        if filters:

            if filters.year:
                mongo_query[
                    "year"
                ] = filters.year

            if filters.language:
                mongo_query[
                    "language"
                ] = filters.language

            if filters.quality:
                mongo_query[
                    "quality"
                ] = filters.quality

            if filters.season:
                mongo_query[
                    "season"
                ] = filters.season

            if filters.episode:
                mongo_query[
                    "episode"
                ] = filters.episode

        cursor = (
            collection
            .find(
                mongo_query
            )
            .limit(
                int(limit)
            )
        )

        return [
            item
            async for item in cursor
        ]

    async def get_by_id(
        self,
        file_id: Any,
    ) -> Optional[dict[str, Any]]:

        if self.db is None:
            raise RuntimeError(
                "FileRepository database is not configured"
            )

        if hasattr(
            self.db,
            "get_file",
        ):
            return await self.db.get_file(
                file_id
            )

        collection = getattr(
            self.db,
            "files",
            None,
        )

        if collection is None:
            collection = getattr(
                self.db,
                "file_col",
                None,
            )

        if collection is None:
            return None

        return await collection.find_one(
            {
                "_id": file_id
            }
        )


# ============================================================================
# Main service
# ============================================================================

class FileSearchService:
    """
    Main file search service.
    """

    def __init__(
        self,
        db=None,
        repository: Optional[
            FileRepository
        ] = None,
    ):
        self.repository = (
            repository
            or FileRepository(db)
        )

        if db is not None:
            self.repository.set_database(
                db
            )

    # ========================================================================
    # Configuration
    # ========================================================================

    def set_database(
        self,
        db,
    ):
        self.repository.set_database(
            db
        )

    # ========================================================================
    # Query handling
    # ========================================================================

    @staticmethod
    def validate_query(
        query: str,
    ) -> str:

        query = str(
            query or ""
        ).strip()

        if len(query) < MIN_QUERY_LENGTH:
            return ""

        return query

    def parse_query(
        self,
        query: str,
    ) -> SearchFilters:

        return QueryNormalizer.extract(
            query
        )

    # ========================================================================
    # Database result normalization
    # ========================================================================

    @staticmethod
    def normalize_document(
        document: dict[str, Any],
    ) -> Optional[SearchResult]:

        if not document:
            return None

        file_id = (
            document.get(
                "file_id"
            )
            or document.get(
                "id"
            )
            or document.get(
                "_id"
            )
        )

        file_name = (
            document.get(
                "file_name"
            )
            or document.get(
                "filename"
            )
            or document.get(
                "name"
            )
            or ""
        )

        if file_id is None:
            return None

        if not file_name:
            file_name = (
                "Unknown File"
            )

        file_size = (
            document.get(
                "file_size"
            )
            or document.get(
                "size"
            )
        )

        chat_id = document.get(
            "chat_id"
        )

        message_id = (
            document.get(
                "message_id"
            )
            or document.get(
                "msg_id"
            )
        )

        reserved = {
            "_id",
            "file_id",
            "id",
            "file_name",
            "filename",
            "name",
            "file_size",
            "size",
            "chat_id",
            "message_id",
            "msg_id",
        }

        metadata = {
            key: value
            for key, value
            in document.items()
            if key not in reserved
        }

        return SearchResult(
            file_id=file_id,
            file_name=str(
                file_name
            ),
            file_size=file_size,
            chat_id=chat_id,
            message_id=message_id,
            metadata=metadata,
        )

    # ========================================================================
    # Filtering
    # ========================================================================

    @staticmethod
    def matches_filters(
        result: SearchResult,
        filters: SearchFilters,
    ) -> bool:

        metadata = result.metadata

        if filters.year is not None:

            value = metadata.get(
                "year"
            )

            if value is not None:
                try:
                    if int(value) != filters.year:
                        return False
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        if filters.language:

            language = str(
                metadata.get(
                    "language",
                    ""
                )
            ).lower()

            filename = result.file_name.lower()

            if (
                filters.language not in language
                and filters.language not in filename
            ):
                return False

        if filters.quality:

            quality = str(
                metadata.get(
                    "quality",
                    ""
                )
            ).lower()

            filename = result.file_name.lower()

            if (
                filters.quality not in quality
                and filters.quality not in filename
            ):
                return False

        if filters.season is not None:

            season = metadata.get(
                "season"
            )

            if season is not None:

                try:
                    if (
                        int(season)
                        != filters.season
                    ):
                        return False
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        if filters.episode is not None:

            episode = metadata.get(
                "episode"
            )

            if episode is not None:

                try:
                    if (
                        int(episode)
                        != filters.episode
                    ):
                        return False
                except (
                    TypeError,
                    ValueError,
                ):
                    pass

        return True

    # ========================================================================
    # Search
    # ========================================================================

    async def search(
        self,
        query: str,
        *,
        limit: int = 100,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> list[SearchResult]:

        query = self.validate_query(
            query
        )

        if not query:
            return []

        filters = self.parse_query(
            query
        )

        try:
            documents = (
                await self.repository.search(
                    filters.clean_query
                    or query,
                    filters=filters,
                    limit=limit,
                )
            )

        except Exception:
            logger.exception(
                "File database search failed for query=%r",
                query,
            )

            return []

        results: list[
            SearchResult
        ] = []

        for document in documents:

            result = (
                self.normalize_document(
                    document
                )
            )

            if result is None:
                continue

            if not self.matches_filters(
                result,
                filters,
            ):
                continue

            result.score = (
                ResultRanker.score(
                    filters.clean_query
                    or query,
                    result.file_name,
                )
            )

            if result.score < score_threshold:
                continue

            results.append(
                result
            )

        results.sort(
            key=lambda item: (
                item.score,
                item.file_name.lower(),
            ),
            reverse=True,
        )

        return results

    # ========================================================================
    # Search without fuzzy threshold
    # ========================================================================

    async def search_exact(
        self,
        query: str,
        *,
        limit: int = 100,
    ) -> list[SearchResult]:

        query = self.validate_query(
            query
        )

        if not query:
            return []

        filters = self.parse_query(
            query
        )

        try:
            documents = (
                await self.repository.search(
                    filters.clean_query
                    or query,
                    filters=filters,
                    limit=limit,
                )
            )

        except Exception:
            logger.exception(
                "Exact file search failed"
            )

            return []

        results = []

        for document in documents:

            result = (
                self.normalize_document(
                    document
                )
            )

            if result is None:
                continue

            if not self.matches_filters(
                result,
                filters,
            ):
                continue

            result.score = (
                ResultRanker.score(
                    filters.clean_query
                    or query,
                    result.file_name,
                )
            )

            results.append(
                result
            )

        results.sort(
            key=lambda item: item.score,
            reverse=True,
        )

        return results

    # ========================================================================
    # Pagination
    # ========================================================================

    @staticmethod
    def paginate(
        results: list[SearchResult],
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str = "",
    ) -> SearchPage:

        try:
            page = int(
                page
            )
        except (
            TypeError,
            ValueError,
        ):
            page = 1

        try:
            page_size = int(
                page_size
            )
        except (
            TypeError,
            ValueError,
        ):
            page_size = DEFAULT_PAGE_SIZE

        page = max(
            1,
            page,
        )

        page_size = max(
            1,
            min(
                page_size,
                MAX_PAGE_SIZE,
            ),
        )

        total = len(
            results
        )

        total_pages = (
            (total + page_size - 1)
            // page_size
            if total
            else 1
        )

        if page > total_pages:
            page = total_pages

        start = (
            (page - 1)
            * page_size
        )

        end = (
            start
            + page_size
        )

        current_results = (
            results[start:end]
        )

        return SearchPage(
            query=query,
            page=page,
            page_size=page_size,
            total=total,
            results=current_results,
            has_previous=(
                page > 1
            ),
            has_next=(
                page < total_pages
            ),
            total_pages=total_pages,
        )

    async def search_page(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SearchPage:

        results = await self.search(
            query,
            limit=MAX_PAGE_SIZE * 10,
        )

        return self.paginate(
            results,
            page=page,
            page_size=page_size,
            query=query,
        )

    # ========================================================================
    # File retrieval
    # ========================================================================

    async def get_file(
        self,
        file_id: Any,
    ) -> Optional[SearchResult]:

        document = (
            await self.repository.get_by_id(
                file_id
            )
        )

        if not document:
            return None

        return self.normalize_document(
            document
        )

    # ========================================================================
    # Result helpers
    # ========================================================================

    @staticmethod
    def get_file_ids(
        results: Iterable[SearchResult],
    ) -> list[Any]:

        return [
            result.file_id
            for result in results
        ]

    @staticmethod
    def get_file_names(
        results: Iterable[SearchResult],
    ) -> list[str]:

        return [
            result.file_name
            for result in results
        ]

    @staticmethod
    def total_results(
        results: Iterable[SearchResult],
    ) -> int:

        return sum(
            1
            for _ in results
        )

    # ========================================================================
    # Streaming interface
    # ========================================================================

    async def iter_search(
        self,
        query: str,
        *,
        limit: int = 100,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> AsyncIterator[SearchResult]:

        results = await self.search(
            query,
            limit=limit,
            score_threshold=score_threshold,
        )

        for result in results:
            yield result

    # ========================================================================
    # Search suggestions
    # ========================================================================

    async def suggest(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> list[str]:

        results = await self.search(
            query,
            limit=limit * 5,
        )

        suggestions = []

        seen = set()

        for result in results:

            name = result.file_name.strip()

            key = name.lower()

            if key in seen:
                continue

            seen.add(
                key
            )

            suggestions.append(
                name
            )

            if len(
                suggestions
            ) >= limit:
                break

        return suggestions


# ============================================================================
# Global service
# ============================================================================

file_search = FileSearchService()


# ============================================================================
# Initialization
# ============================================================================

def initialize_file_search(
    db,
) -> FileSearchService:

    file_search.set_database(
        db
    )

    return file_search


# ============================================================================
# Convenience functions
# ============================================================================

async def search_files(
    query: str,
    *,
    limit: int = 100,
) -> list[SearchResult]:

    return await file_search.search(
        query,
        limit=limit,
    )


async def search_files_page(
    query: str,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> SearchPage:

    return await file_search.search_page(
        query,
        page=page,
        page_size=page_size,
    )


async def get_file(
    file_id: Any,
) -> Optional[SearchResult]:

    return await file_search.get_file(
        file_id
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "SearchFilters",
    "SearchResult",
    "SearchPage",
    "QueryNormalizer",
    "ResultRanker",
    "FileRepository",
    "FileSearchService",
    "file_search",
    "initialize_file_search",
    "search_files",
    "search_files_page",
    "get_file",
]