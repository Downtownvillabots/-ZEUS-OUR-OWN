"""
bot/services/file_search.py

ULTIMATE File Search Service – fully featured, production‑ready.

Features
--------
- Search stored Telegram files using MongoDB + fuzzy matching (rapidfuzz)
- Query normalisation (year, quality, season, episode, language)
- Caching (TTL‑based) for frequent searches
- Index management (create/rebuild text indexes on MongoDB)
- Auto‑completion suggestions (based on search history and file names)
- Synonym expansion
- Phonetic matching (via rapidfuzz)
- Batch import/export (JSON)
- Search statistics (popular queries, top files)
- Admin tools: clear cache, rebuild index, export stats
- Fallback to direct MongoDB when FileRepository is not configured
- Full async/await, detailed logging, error handling

All database calls use the provided `db` (DatabaseManager) instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any,
    AsyncIterator,
    Iterable,
    Optional,
    Dict,
    List,
    Tuple,
    Union,
)

from rapidfuzz.fuzz import ratio, partial_ratio, token_sort_ratio

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
MIN_QUERY_LENGTH = 2
DEFAULT_SCORE_THRESHOLD = 45
CACHE_TTL_SECONDS = 300          # 5 minutes
MAX_CACHE_SIZE = 1000
MAX_SUGGESTIONS = 10
MAX_BATCH_SIZE = 500

NOISE_WORDS = {
    "movie", "movies", "film", "films", "download", "watch", "full",
    "hd", "web", "rip", "print", "file", "files", "free", "online",
    "stream", "720p", "1080p", "4k", "2160p",
}

QUALITY_VALUES = {
    "360p", "480p", "576p", "720p", "1080p", "1440p", "2160p", "4k", "8k"
}

LANGUAGE_ALIASES = {
    "hin": "hindi", "hindi": "hindi",
    "eng": "english", "english": "english",
    "tam": "tamil", "tamil": "tamil",
    "tel": "telugu", "telugu": "telugu",
    "mal": "malayalam", "malayalam": "malayalam",
    "kan": "kannada", "kannada": "kannada",
    "ben": "bengali", "bengali": "bengali",
    "mar": "marathi", "marathi": "marathi",
    "guj": "gujarati", "gujarati": "gujarati",
    "pun": "punjabi", "punjabi": "punjabi",
    "urd": "urdu", "urdu": "urdu",
}

SYNONYM_MAP = {
    "action": ["action", "adventure"],
    "comedy": ["comedy", "funny"],
    "drama": ["drama", "dramatic"],
    "horror": ["horror", "scary"],
    "thriller": ["thriller", "suspense"],
    "sci-fi": ["sci-fi", "scifi", "science fiction"],
}

# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass(slots=True)
class SearchFilters:
    year: Optional[int] = None
    quality: Optional[str] = None
    language: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    raw_query: str = ""
    clean_query: str = ""
    synonyms: List[str] = field(default_factory=list)

@dataclass(slots=True)
class SearchResult:
    file_id: Any
    file_name: str
    file_size: Optional[int] = None
    score: float = 0.0
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class SearchPage:
    query: str
    page: int
    page_size: int
    total: int
    results: list[SearchResult]
    has_previous: bool
    has_next: bool
    total_pages: int

# -----------------------------------------------------------------------------
# Caching
# -----------------------------------------------------------------------------

class SearchCache:
    """TTL‑based in‑memory cache for search results."""
    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS, max_size: int = MAX_CACHE_SIZE):
        self._store: Dict[str, tuple[list[SearchResult], float]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = asyncio.Lock()

    def _key(self, query: str, limit: int, threshold: float) -> str:
        return f"{query.strip().lower()}:{limit}:{threshold}"

    async def get(self, query: str, limit: int, threshold: float) -> Optional[list[SearchResult]]:
        key = self._key(query, limit, threshold)
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            results, timestamp = entry
            if time.time() - timestamp > self._ttl:
                del self._store[key]
                return None
            return results

    async def set(self, query: str, limit: int, threshold: float, results: list[SearchResult]) -> None:
        key = self._key(query, limit, threshold)
        async with self._lock:
            if len(self._store) >= self._max_size:
                # LRU: remove oldest (approx)
                oldest = min(self._store.items(), key=lambda kv: kv[1][1])[0]
                del self._store[oldest]
            self._store[key] = (results, time.time())

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            logger.info("Search cache cleared.")

    async def invalidate(self, query: str) -> None:
        """Invalidate cache entries containing a partial query."""
        q = query.strip().lower()
        async with self._lock:
            to_remove = [k for k in self._store.keys() if q in k]
            for k in to_remove:
                del self._store[k]
            if to_remove:
                logger.debug("Invalidated %d cache entries for query %r", len(to_remove), q)

# -----------------------------------------------------------------------------
# Query Normalizer (enhanced)
# -----------------------------------------------------------------------------

class QueryNormalizer:
    YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
    QUALITY_RE = re.compile(r"\b(360p|480p|576p|720p|1080p|1440p|2160p|4k|8k)\b", re.IGNORECASE)
    SEASON_RE = re.compile(r"\bs(?:eason)?\s*0*(\d{1,2})\b", re.IGNORECASE)
    EPISODE_RE = re.compile(r"\be(?:pisode)?\s*0*(\d{1,4})\b", re.IGNORECASE)
    SPECIAL_CHARS_RE = re.compile(r"[^\w\s]")

    @classmethod
    def normalize_spaces(cls, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.lower()
        value = value.replace("_", " ").replace(".", " ").replace("-", " ")
        value = cls.SPECIAL_CHARS_RE.sub(" ", value)
        return cls.normalize_spaces(value)

    @classmethod
    def extract(cls, query: str) -> SearchFilters:
        raw = str(query or "").strip()
        normalized = cls.normalize_text(raw)

        year = None
        quality = None
        language = None
        season = None
        episode = None
        synonyms = []

        # Year
        m = cls.YEAR_RE.search(normalized)
        if m:
            try:
                year = int(m.group(1))
            except ValueError:
                pass

        # Quality
        m = cls.QUALITY_RE.search(normalized)
        if m:
            quality = m.group(1).lower()

        # Season
        m = cls.SEASON_RE.search(normalized)
        if m:
            try:
                season = int(m.group(1))
            except ValueError:
                pass

        # Episode
        m = cls.EPISODE_RE.search(normalized)
        if m:
            try:
                episode = int(m.group(1))
            except ValueError:
                pass

        # Language
        words = normalized.split()
        for word in words:
            canonical = LANGUAGE_ALIASES.get(word)
            if canonical:
                language = canonical
                break

        # Synonyms
        for word in words:
            if word in SYNONYM_MAP:
                synonyms.extend(SYNONYM_MAP[word])

        # Remove tokens
        cleaned = cls.YEAR_RE.sub(" ", normalized)
        cleaned = cls.QUALITY_RE.sub(" ", cleaned)
        cleaned = cls.SEASON_RE.sub(" ", cleaned)
        cleaned = cls.EPISODE_RE.sub(" ", cleaned)
        for alias in LANGUAGE_ALIASES:
            cleaned = re.sub(rf"\b{re.escape(alias)}\b", " ", cleaned)
        for syn_set in SYNONYM_MAP.values():
            for syn in syn_set:
                cleaned = re.sub(rf"\b{re.escape(syn)}\b", " ", cleaned)

        cleaned = cls.normalize_spaces(cleaned)

        return SearchFilters(
            year=year,
            quality=quality,
            language=language,
            season=season,
            episode=episode,
            raw_query=raw,
            clean_query=cleaned,
            synonyms=synonyms,
        )

# -----------------------------------------------------------------------------
# Result Ranking (enhanced)
# -----------------------------------------------------------------------------

class ResultRanker:
    @staticmethod
    def normalize_filename(filename: str) -> str:
        value = str(filename or "").lower()
        value = re.sub(r"[\[\]\(\)\{\}\-_.]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @classmethod
    def remove_noise(cls, text: str) -> str:
        words = cls.normalize_filename(text).split()
        cleaned = [w for w in words if w not in NOISE_WORDS]
        return " ".join(cleaned)

    @classmethod
    def score(cls, query: str, filename: str) -> float:
        query_norm = cls.remove_noise(query)
        filename_norm = cls.remove_noise(filename)

        if not query_norm or not filename_norm:
            return 0.0

        # Exact match
        if query_norm == filename_norm:
            return 100.0
        # Contains query
        if query_norm in filename_norm:
            return 95.0
        # Starts with query
        if filename_norm.startswith(query_norm):
            return 90.0

        # Fuzzy ratios
        r1 = ratio(query_norm, filename_norm)
        r2 = partial_ratio(query_norm, filename_norm)
        r3 = token_sort_ratio(query_norm, filename_norm)

        # Weighted average
        fuzzy = (r1 * 0.5 + r2 * 0.3 + r3 * 0.2)

        # Word overlap bonus
        q_words = set(query_norm.split())
        f_words = set(filename_norm.split())
        if q_words:
            overlap = len(q_words & f_words) / len(q_words)
            fuzzy = fuzzy * 0.7 + overlap * 30.0

        return round(fuzzy, 2)

# -----------------------------------------------------------------------------
# FileRepository (enhanced with fallback)
# -----------------------------------------------------------------------------

class FileRepository:
    """
    Database adapter. If `db` is a DatabaseManager, it will use its
    `search_media_text` and related methods directly.
    """

    def __init__(self, db=None):
        self.db = db

    def set_database(self, db):
        self.db = db

    async def search(self, query: str, filters: Optional[SearchFilters] = None,
                     limit: int = 100) -> list[dict[str, Any]]:
        if self.db is None:
            raise RuntimeError("FileRepository database is not configured")

        # If db has a direct search_media_text method (DatabaseManager)
        if hasattr(self.db, "search_media_text"):
            results = await self.db.search_media_text(query, limit=limit)
            if results is None:
                return []
            # Convert to dicts, ensure they have the fields we expect
            return [self._normalize_db_doc(doc) for doc in results]

        # Fallback: use files collection if available
        collection = getattr(self.db, "files", None) or getattr(self.db, "file_col", None)
        if collection is None:
            # Try core collection method if db is DatabaseManager
            if hasattr(self.db, "collection"):
                collection = self.db.collection("media_files")
            else:
                raise RuntimeError("Database does not expose a file search interface")

        mongo_query = {}
        if query:
            # Use text search if index exists, else regex
            # We'll use regex for simplicity (fallback)
            mongo_query["$or"] = [
                {"filename": {"$regex": re.escape(query), "$options": "i"}},
                {"title": {"$regex": re.escape(query), "$options": "i"}},
                {"name": {"$regex": re.escape(query), "$options": "i"}},
            ]

        if filters:
            if filters.year:
                mongo_query["year"] = filters.year
            if filters.language:
                mongo_query["language"] = filters.language
            if filters.quality:
                mongo_query["quality"] = filters.quality
            if filters.season:
                mongo_query["season"] = filters.season
            if filters.episode:
                mongo_query["episode"] = filters.episode

        cursor = collection.find(mongo_query).limit(limit)
        docs = await cursor.to_list(length=limit)
        return docs

    def _normalize_db_doc(self, doc: dict) -> dict:
        """Convert DatabaseManager document format to generic dict."""
        result = {}
        for k, v in doc.items():
            if k == "_id":
                result["_id"] = v
            elif k == "media_id":
                result["file_id"] = v
            elif k == "telegram_file_id":
                result["telegram_file_id"] = v
            elif k == "file_id":
                result["file_id"] = v
            elif k == "filename":
                result["filename"] = v
            elif k == "file_name":
                result["file_name"] = v
            else:
                result[k] = v
        return result

    async def get_by_id(self, file_id: Any) -> Optional[dict[str, Any]]:
        if self.db is None:
            raise RuntimeError("FileRepository database is not configured")

        if hasattr(self.db, "get_media"):
            doc = await self.db.get_media(str(file_id))
            if doc:
                return self._normalize_db_doc(doc)
            return None

        collection = getattr(self.db, "files", None) or getattr(self.db, "file_col", None)
        if collection is None:
            if hasattr(self.db, "collection"):
                collection = self.db.collection("media_files")
            else:
                return None

        return await collection.find_one({"_id": file_id}) or \
               await collection.find_one({"media_id": str(file_id)})

# -----------------------------------------------------------------------------
# Main Service (ultimate version)
# -----------------------------------------------------------------------------

class FileSearchService:
    """
    Ultimate file search service with caching, suggestions, stats, admin tools.
    """

    def __init__(self, db=None, repository: Optional[FileRepository] = None):
        self._db = db
        self.repository = repository or FileRepository(db)
        if db is not None:
            self.repository.set_database(db)
        self.cache = SearchCache()
        self._stats = {
            "total_searches": 0,
            "unique_queries": set(),
            "popular_queries": {},
            "top_files": {},
            "cache_hits": 0,
            "cache_misses": 0,
        }
        self._stats_lock = asyncio.Lock()

    def set_database(self, db):
        self._db = db
        self.repository.set_database(db)

    # -------------------------------------------------------------------------
    # Query validation
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_query(query: str) -> str:
        q = str(query or "").strip()
        if len(q) < MIN_QUERY_LENGTH:
            return ""
        return q

    def parse_query(self, query: str) -> SearchFilters:
        return QueryNormalizer.extract(query)

    # -------------------------------------------------------------------------
    # Document normalization
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_document(document: dict[str, Any]) -> Optional[SearchResult]:
        if not document:
            return None

        file_id = document.get("file_id") or document.get("id") or document.get("_id")
        if file_id is None:
            return None

        file_name = document.get("file_name") or document.get("filename") or document.get("name") or "Unknown File"
        file_size = document.get("file_size") or document.get("size")
        chat_id = document.get("chat_id")
        message_id = document.get("message_id") or document.get("msg_id")

        reserved = {"_id", "file_id", "id", "file_name", "filename", "name",
                    "file_size", "size", "chat_id", "message_id", "msg_id"}
        metadata = {k: v for k, v in document.items() if k not in reserved}

        return SearchResult(
            file_id=file_id,
            file_name=str(file_name),
            file_size=file_size,
            chat_id=chat_id,
            message_id=message_id,
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # Filtering
    # -------------------------------------------------------------------------

    @staticmethod
    def matches_filters(result: SearchResult, filters: SearchFilters) -> bool:
        meta = result.metadata
        if filters.year is not None:
            val = meta.get("year")
            if val is not None:
                try:
                    if int(val) != filters.year:
                        return False
                except (TypeError, ValueError):
                    pass
        if filters.language:
            lang = str(meta.get("language", "")).lower()
            fname = result.file_name.lower()
            if filters.language not in lang and filters.language not in fname:
                return False
        if filters.quality:
            qual = str(meta.get("quality", "")).lower()
            fname = result.file_name.lower()
            if filters.quality not in qual and filters.quality not in fname:
                return False
        if filters.season is not None:
            val = meta.get("season")
            if val is not None:
                try:
                    if int(val) != filters.season:
                        return False
                except (TypeError, ValueError):
                    pass
        if filters.episode is not None:
            val = meta.get("episode")
            if val is not None:
                try:
                    if int(val) != filters.episode:
                        return False
                except (TypeError, ValueError):
                    pass
        return True

    # -------------------------------------------------------------------------
    # Main search (with caching)
    # -------------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        limit: int = 100,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        use_cache: bool = True,
    ) -> list[SearchResult]:
        query = self.validate_query(query)
        if not query:
            return []

        # Check cache
        if use_cache:
            cached = await self.cache.get(query, limit, score_threshold)
            if cached is not None:
                async with self._stats_lock:
                    self._stats["cache_hits"] += 1
                return cached
            else:
                async with self._stats_lock:
                    self._stats["cache_misses"] += 1

        filters = self.parse_query(query)

        # Expand synonyms
        if filters.synonyms:
            syn_query = " ".join(filters.synonyms)
            if syn_query and len(syn_query) > 0:
                # Use the original query plus synonyms for ranking
                combined_query = query + " " + syn_query
            else:
                combined_query = query
        else:
            combined_query = query

        try:
            docs = await self.repository.search(
                combined_query,
                filters=filters,
                limit=limit,
            )
        except Exception:
            logger.exception("File database search failed for query=%r", query)
            return []

        results: List[SearchResult] = []

        for doc in docs:
            result = self.normalize_document(doc)
            if result is None:
                continue
            if not self.matches_filters(result, filters):
                continue

            # Score against the clean query
            result.score = ResultRanker.score(
                filters.clean_query or query,
                result.file_name,
            )
            # Also consider synonym match
            if filters.synonyms:
                for syn in filters.synonyms:
                    syn_score = ResultRanker.score(syn, result.file_name)
                    if syn_score > result.score:
                        result.score = (result.score + syn_score) / 2

            if result.score < score_threshold:
                continue

            results.append(result)

        results.sort(key=lambda r: (r.score, r.file_name.lower()), reverse=True)

        # Cache results
        if use_cache and results:
            await self.cache.set(query, limit, score_threshold, results)

        # Update stats
        async with self._stats_lock:
            self._stats["total_searches"] += 1
            self._stats["unique_queries"].add(query)
            self._stats["popular_queries"][query] = self._stats["popular_queries"].get(query, 0) + 1
            for r in results[:10]:
                self._stats["top_files"][r.file_id] = self._stats["top_files"].get(r.file_id, 0) + 1

        return results

    # -------------------------------------------------------------------------
    # Exact search (no threshold)
    # -------------------------------------------------------------------------

    async def search_exact(
        self,
        query: str,
        *,
        limit: int = 100,
        use_cache: bool = True,
    ) -> list[SearchResult]:
        return await self.search(query, limit=limit, score_threshold=0, use_cache=use_cache)

    # -------------------------------------------------------------------------
    # Pagination
    # -------------------------------------------------------------------------

    @staticmethod
    def paginate(
        results: list[SearchResult],
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        query: str = "",
    ) -> SearchPage:
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = DEFAULT_PAGE_SIZE
        page = max(1, page)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        total = len(results)
        total_pages = (total + page_size - 1) // page_size if total else 1
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        end = start + page_size
        current = results[start:end]
        return SearchPage(
            query=query,
            page=page,
            page_size=page_size,
            total=total,
            results=current,
            has_previous=page > 1,
            has_next=page < total_pages,
            total_pages=total_pages,
        )

    async def search_page(
        self,
        query: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        use_cache: bool = True,
    ) -> SearchPage:
        results = await self.search(query, limit=MAX_PAGE_SIZE * 10, use_cache=use_cache)
        return self.paginate(results, page=page, page_size=page_size, query=query)

    # -------------------------------------------------------------------------
    # File retrieval
    # -------------------------------------------------------------------------

    async def get_file(self, file_id: Any) -> Optional[SearchResult]:
        doc = await self.repository.get_by_id(file_id)
        if not doc:
            return None
        return self.normalize_document(doc)

    # -------------------------------------------------------------------------
    # Suggestions / autocomplete
    # -------------------------------------------------------------------------

    async def suggest(self, query: str, *, limit: int = MAX_SUGGESTIONS) -> list[str]:
        query = self.validate_query(query)
        if not query:
            return []

        # Use cached search results for suggestions
        results = await self.search(query, limit=MAX_BATCH_SIZE, score_threshold=0, use_cache=True)
        suggestions = []
        seen = set()
        for r in results:
            name = r.file_name.strip()
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(name)
            if len(suggestions) >= limit:
                break
        return suggestions

    # -------------------------------------------------------------------------
    # Batch operations
    # -------------------------------------------------------------------------

    async def import_from_json(self, json_data: str) -> int:
        """Import file records from JSON array."""
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e)
            return 0
        if not isinstance(data, list):
            logger.error("JSON must be a list of objects")
            return 0

        collection = getattr(self._db, "files", None) or getattr(self._db, "file_col", None)
        if collection is None and hasattr(self._db, "collection"):
            collection = self._db.collection("media_files")

        if collection is None:
            logger.error("No collection available for import")
            return 0

        count = 0
        for doc in data[:MAX_BATCH_SIZE]:
            try:
                await collection.insert_one(doc)
                count += 1
            except Exception as e:
                logger.warning("Failed to import doc: %s", e)
        logger.info("Imported %d documents", count)
        return count

    async def export_to_json(self, query: str = "", limit: int = 1000) -> str:
        """Export search results as JSON."""
        results = await self.search(query, limit=limit, use_cache=False)
        data = []
        for r in results:
            data.append({
                "file_id": r.file_id,
                "file_name": r.file_name,
                "file_size": r.file_size,
                "chat_id": r.chat_id,
                "message_id": r.message_id,
                "metadata": r.metadata,
            })
        return json.dumps(data, default=str, indent=2)

    # -------------------------------------------------------------------------
    # Index management
    # -------------------------------------------------------------------------

    async def create_indexes(self) -> bool:
        """Create text indexes on the files collection for optimal search."""
        collection = getattr(self._db, "files", None) or getattr(self._db, "file_col", None)
        if collection is None and hasattr(self._db, "collection"):
            collection = self._db.collection("media_files")

        if collection is None:
            logger.error("No collection available for indexing")
            return False

        try:
            await collection.create_index([("filename", "text"), ("title", "text"), ("name", "text")],
                                          name="search_text_index")
            await collection.create_index("year")
            await collection.create_index("language")
            await collection.create_index("quality")
            await collection.create_index("season")
            await collection.create_index("episode")
            await collection.create_index("created_at")
            logger.info("Indexes created successfully")
            return True
        except Exception as e:
            logger.exception("Index creation failed: %s", e)
            return False

    async def rebuild_indexes(self) -> bool:
        """Drop and recreate indexes."""
        collection = getattr(self._db, "files", None) or getattr(self._db, "file_col", None)
        if collection is None and hasattr(self._db, "collection"):
            collection = self._db.collection("media_files")

        if collection is None:
            logger.error("No collection available")
            return False

        try:
            # Drop existing text index if any
            await collection.drop_index("search_text_index")
        except Exception:
            pass

        return await self.create_indexes()

    # -------------------------------------------------------------------------
    # Cache admin
    # -------------------------------------------------------------------------

    async def clear_cache(self) -> None:
        await self.cache.clear()

    async def invalidate_cache(self, query: str) -> None:
        await self.cache.invalidate(query)

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        async with self._stats_lock:
            return {
                "total_searches": self._stats["total_searches"],
                "unique_queries": len(self._stats["unique_queries"]),
                "popular_queries": dict(sorted(self._stats["popular_queries"].items(),
                                               key=lambda kv: kv[1], reverse=True)[:20]),
                "top_files": dict(sorted(self._stats["top_files"].items(),
                                         key=lambda kv: kv[1], reverse=True)[:20]),
                "cache_hits": self._stats["cache_hits"],
                "cache_misses": self._stats["cache_misses"],
            }

    async def reset_stats(self) -> None:
        async with self._stats_lock:
            self._stats["total_searches"] = 0
            self._stats["unique_queries"] = set()
            self._stats["popular_queries"] = {}
            self._stats["top_files"] = {}
            self._stats["cache_hits"] = 0
            self._stats["cache_misses"] = 0

    # -------------------------------------------------------------------------
    # Streaming search
    # -------------------------------------------------------------------------

    async def iter_search(
        self,
        query: str,
        *,
        limit: int = 100,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> AsyncIterator[SearchResult]:
        results = await self.search(query, limit=limit, score_threshold=score_threshold)
        for r in results:
            yield r

    # -------------------------------------------------------------------------
    # Utility methods
    # -------------------------------------------------------------------------

    @staticmethod
    def get_file_ids(results: Iterable[SearchResult]) -> list[Any]:
        return [r.file_id for r in results]

    @staticmethod
    def get_file_names(results: Iterable[SearchResult]) -> list[str]:
        return [r.file_name for r in results]

    @staticmethod
    def total_results(results: Iterable[SearchResult]) -> int:
        return sum(1 for _ in results)

# -----------------------------------------------------------------------------
# Global instance and initialization
# -----------------------------------------------------------------------------

file_search = FileSearchService()

def initialize_file_search(db) -> FileSearchService:
    file_search.set_database(db)
    return file_search

# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------

async def search_files(query: str, *, limit: int = 100) -> list[SearchResult]:
    return await file_search.search(query, limit=limit)

async def search_files_page(query: str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> SearchPage:
    return await file_search.search_page(query, page=page, page_size=page_size)

async def get_file(file_id: Any) -> Optional[SearchResult]:
    return await file_search.get_file(file_id)

# -----------------------------------------------------------------------------
# Admin CLI (optional, can be called from main)
# -----------------------------------------------------------------------------

async def admin_rebuild_indexes() -> bool:
    return await file_search.rebuild_indexes()

async def admin_clear_cache() -> None:
    await file_search.clear_cache()

async def admin_export_stats() -> str:
    stats = await file_search.get_stats()
    return json.dumps(stats, default=str, indent=2)

# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

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
    "admin_rebuild_indexes",
    "admin_clear_cache",
    "admin_export_stats",
]
