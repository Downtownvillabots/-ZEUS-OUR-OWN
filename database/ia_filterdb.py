import logging
import asyncio
import re
import base64
from struct import pack
from typing import Dict, List, Optional, Tuple, Union, Any
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, PyMongoError, ConnectionFailure, OperationFailure
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from umongo import Instance, Document, fields, ValidationError

# Import project settings
from utils import get_settings, save_group_settings
from info import (
    COLLECTION_NAME, COVERX, DATABASE_NAME, DATABASE_URI, DATABASE_URI2, DATABASE_URI3,
    INDEX_CAPTION, MAX_B_TN, MULTIPLE_DB, ULTRA_FAST_MODE, USE_CAPTION_FILTER,
    DATABASE_URIS  # dynamic list of all URIs
)

# ============================================================
# LOGGING & CACHE CONFIGURATION
# ============================================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_db_stats_cache = {"timestamp": None, "primary_size": 0.0}

# Search result cache (future optimization)
_search_cache: Dict[str, Tuple[float, list, int]] = {}
_SEARCH_CACHE_TTL = 60  # seconds

# ============================================================
# HELPER: REGEX CACHE
# ============================================================
@lru_cache(maxsize=4096)
def compile_regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)

# ============================================================
# DYNAMIC DATABASE POOL (UNLIMITED SUPPORT)
# ============================================================
_all_clients: List[AsyncIOMotorClient] = []
_all_dbs: List[AsyncIOMotorDatabase] = []
_all_instances: List[Instance] = []
_all_models: List[type] = []

def _create_model(instance: Instance) -> type:
    """Create and register a Media model with the given umongo instance."""
    class MediaModel(Document):
        file_id = fields.StrField(attribute="_id")
        file_ref = fields.StrField(allow_none=True)
        file_name = fields.StrField(required=True)
        file_size = fields.IntField(required=True)
        file_type = fields.StrField(allow_none=True)
        mime_type = fields.StrField(allow_none=True)
        caption = fields.StrField(allow_none=True)
        cover = fields.StrField(allow_none=True)

        class Meta:
            collection_name = COLLECTION_NAME

        @classmethod
        async def ensure_indexes(cls):
            """Create the required index on file_name."""
            try:
                if cls.collection is not None:
                    await cls.collection.create_index([("file_name", 1)])
            except Exception as e:
                logger.error(f"Index creation failed for {cls.collection.name}: {e}")
                # Fallback: try text index
                try:
                    await cls.collection.create_index([("file_name", "text")])
                except Exception:
                    pass

    # `instance.register` returns the registered model (not the template)
    return instance.register(MediaModel)

def _initialize_database_pool():
    """Initialize all database connections from the URIs."""
    global _all_clients, _all_dbs, _all_instances, _all_models

    for uri in DATABASE_URIS:
        try:
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            db = client[DATABASE_NAME]
            instance = Instance.from_db(db)
            _all_clients.append(client)
            _all_dbs.append(db)
            _all_instances.append(instance)
        except Exception as e:
            logger.error(f"Failed to connect to DB at {uri}: {e}")

    # If no DBs available, raise a clear error
    if not _all_dbs:
        raise RuntimeError("No valid MongoDB connection found.")

    # Create models for each database
    for db in _all_dbs:
        inst = Instance.from_db(db)
        model = _create_model(inst)
        _all_models.append(model)

# Initialize on import
_initialize_database_pool()

# Backward compatibility aliases
Media = _all_models[0] if _all_models else None
Media2 = _all_models[1] if len(_all_models) > 1 else Media
Media3 = _all_models[2] if len(_all_models) > 2 else Media2

db = _all_dbs[0] if _all_dbs else None
db2 = _all_dbs[1] if len(_all_dbs) > 1 else db
db3 = _all_dbs[2] if len(_all_dbs) > 2 else db2

DBS = _all_dbs
MODELS = _all_models
COLLECTIONS = [db[COLLECTION_NAME] for db in _all_dbs]

# ============================================================
# DATABASE HEALTH & SIZE
# ============================================================
async def check_db_size(database: AsyncIOMotorDatabase) -> float:
    """Return the database size in MB with caching."""
    try:
        now = datetime.utcnow()
        cache_stale = (
            _db_stats_cache["timestamp"] is None
            or (now - _db_stats_cache["timestamp"] > timedelta(minutes=10))
        )
        # Force refresh if primary size >= 10 MB
        force_refresh = _db_stats_cache["primary_size"] >= 10.0

        if not cache_stale and not force_refresh:
            return _db_stats_cache["primary_size"]

        stats = await database.command("dbstats")
        size_mb = (stats["dataSize"] + stats["indexSize"]) / (1024 * 1024)
        _db_stats_cache["primary_size"] = size_mb
        _db_stats_cache["timestamp"] = now
        return size_mb
    except Exception as e:
        logger.exception(f"Error checking DB size: {e}")
        return 0

async def ping_databases() -> List[Tuple[int, bool]]:
    """Check health of all databases."""
    results = []
    for idx, database in enumerate(DBS):
        try:
            await database.command("ping")
            results.append((idx, True))
        except Exception:
            results.append((idx, False))
    return results

# ============================================================
# SAVE FILE (with full error handling)
# ============================================================
async def save_file(media) -> Tuple[bool, int]:
    """
    Save file to the database.
    Returns: (success, status_code)
    Status codes:
        0 - duplicate
        1 - success
        2 - validation error
        3 - other error
    """
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
    except Exception as e:
        logger.exception(f"Failed to unpack file ID: {e}")
        return False, 3

    # Clean filename
    file_name = re.sub(
        r"[_\-\.#+$%^&*()!~`,;:\"'?/<>\[\]{}=|\\]", " ", str(media.file_name)
    )
    file_name = re.sub(r"\s+", " ", file_name).strip()

    if not file_name:
        file_name = "Unknown File"

    # Check duplicates across all databases
    for idx, model in enumerate(MODELS):
        try:
            exists = await model.collection.find_one({"file_id": file_id})
            if exists:
                logger.info(f"[SKIP] '{file_name}' already in DB{idx+1}.")
                return False, 0
        except Exception as e:
            logger.error(f"Duplicate check error in DB{idx+1}: {e}")

    # Choose the smallest database (by size)
    target_index = 0
    if len(DBS) > 1:
        min_size = float("inf")
        for idx, database in enumerate(DBS):
            size = await check_db_size(database)
            if size < min_size:
                min_size = size
                target_index = idx

    target_model = MODELS[target_index]
    target_db_name = f"DB{target_index+1}"

    try:
        cover_to_use = getattr(getattr(media, "cover", None), "file_id", None)
        record = target_model(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=getattr(media, "file_size", 0),
            file_type=getattr(media, "file_type", None),
            mime_type=getattr(media, "mime_type", None),
            caption=(media.caption.html if media.caption and INDEX_CAPTION else None),
            cover=cover_to_use if COVERX else None,
        )
    except ValidationError as e:
        logger.exception(f"[VALIDATION ERROR] '{file_name}': {e}")
        return False, 2
    except Exception as e:
        logger.exception(f"[ERROR] '{file_name}' - {e}")
        return False, 3

    try:
        await record.commit()
        logger.info(f"[SUCCESS] '{file_name}' saved to {target_db_name}.")
        return True, 1
    except DuplicateKeyError:
        logger.info(f"[SKIP] DuplicateKey: '{file_name}' already exists in {target_db_name}.")
        return False, 0
    except OperationFailure as e:
        logger.exception(f"[DB ERROR] {target_db_name}: {e}")
        # Retry with next DB
        if target_index + 1 < len(MODELS):
            try:
                record2 = MODELS[target_index + 1](**record.to_mongo())
                await record2.commit()
                return True, 1
            except Exception:
                pass
        return False, 3
    except Exception as e:
        logger.exception(f"[ERROR] Failed commit of '{file_name}' to {target_db_name}: {e}")
        return False, 3

# ============================================================
# GET SEARCH RESULTS (with caching and error handling)
# ============================================================
async def get_search_results(
    chat_id,
    query,
    file_type=None,
    max_results=None,
    offset=0,
    filter=False,
):
    """
    Search across all databases.
    Returns (files, next_offset, total_results).
    """
    # Settings for max_results
    if chat_id is not None and max_results is None:
        settings = await get_settings(int(chat_id))
        if "max_btn" not in settings:
            await save_group_settings(int(chat_id), "max_btn", True)
            settings["max_btn"] = True
        max_results = 10 if settings["max_btn"] else int(MAX_B_TN)

    # Build regex
    if isinstance(query, list):
        raw_pattern = "|".join(re.escape(q.strip()) for q in query if q and q.strip())
        if not raw_pattern:
            return [], None, 0
        regex = compile_regex(raw_pattern)
        if USE_CAPTION_FILTER:
            filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]}
        else:
            filter_mongo = {"file_name": regex}
    else:
        query = query.strip()
        if not query:
            return [], None, 0
        if " " in query:
            words = [re.escape(w) for w in query.split() if w]
            raw_pattern = (r".*[\s\.\+\-_]".join(words) if words else r".")
        else:
            raw_pattern = (r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])")
        try:
            regex = compile_regex(raw_pattern)
        except re.error:
            return [], None, 0
        if USE_CAPTION_FILTER:
            filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]}
        else:
            filter_mongo = {"file_name": regex}

    if file_type:
        filter_mongo["file_type"] = file_type

    # Check cache
    cache_key = f"{query}|{file_type}|{max_results}|{offset}|{chat_id}"
    cached = _search_cache.get(cache_key)
    if cached and (time.time() - cached[0] < _SEARCH_CACHE_TTL):
        return cached[1], cached[2], cached[3]

    # Perform search across all DBs
    try:
        if ULTRA_FAST_MODE:
            limit = max_results + 1
            fetch_limit = offset + limit
            tasks = [
                model.collection.find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for model in MODELS
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            files = []
            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"Search DB error: {res}")
                    continue
                files.extend(res)
            files = files[offset:offset + limit]
            has_next = len(files) > max_results
            if has_next:
                files = files[:-1]
            next_offset = offset + len(files) if has_next else ""
            total_results = offset + len(files) + (1 if has_next else 0)
        else:
            fetch_limit = offset + max_results
            count_tasks = [
                model.collection.count_documents(filter_mongo)
                for model in MODELS
            ]
            find_tasks = [
                model.collection.find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for model in MODELS
            ]
            count_results, find_results = await asyncio.gather(
                asyncio.gather(*count_tasks, return_exceptions=True),
                asyncio.gather(*find_tasks, return_exceptions=True),
            )
            total_results = 0
            for cr in count_results:
                if isinstance(cr, Exception):
                    logger.error(f"Count error: {cr}")
                else:
                    total_results += cr

            files = []
            for fr in find_results:
                if isinstance(fr, Exception):
                    logger.error(f"Find error: {fr}")
                else:
                    files.extend(fr)
            files = files[offset:offset + max_results]
            next_offset = offset + len(files)
            if next_offset >= total_results:
                next_offset = ""
    except Exception as e:
        logger.exception(f"Search failed: {e}")
        return [], "", 0

    # Store in cache
    _search_cache[cache_key] = (time.time(), files, next_offset, total_results)

    return files, next_offset, total_results

# ============================================================
# GET BAD FILES (for deletefiles command)
# ============================================================
async def get_bad_files(query, file_type=None):
    query = query.strip()
    if not query:
        return [], 0

    # Build regex
    if " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = r".*[\s\.\+\-_]".join(map(re.escape, query.split()))
    try:
        regex = compile_regex(raw_pattern)
    except re.error:
        return [], 0

    if USE_CAPTION_FILTER:
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]}
    else:
        filter_mongo = {"file_name": regex}
    if file_type:
        filter_mongo["file_type"] = file_type

    # Fetch from all DBs
    tasks = [
        model.collection.find(filter_mongo)
        .sort("$natural", -1)
        .to_list(300)
        for model in MODELS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    files = []
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Bad files error: {res}")
            continue
        files.extend(res)
    files = files[:300]
    return files, len(files)

# ============================================================
# GET FILE DETAILS (with fallback across DBs)
# ============================================================
async def get_file_details(query):
    filter = {"file_id": query}
    tasks = [
        model.collection.find(filter).to_list(length=1)
        for model in MODELS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"File details error: {res}")
            continue
        if res:
            return res
    return []

# ============================================================
# FILE ID ENCODING / DECODING (unchanged)
# ============================================================
def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref

# ============================================================
# DOWNTOWN VILLA MEDIA HELPERS
# ============================================================
async def dreamxbotz_fetch_media(limit: int = 20) -> List[dict]:
    """Fetch recent media from the least full DB."""
    try:
        # Try to find DB under 407 MB
        if len(DBS) > 1:
            for idx, database in enumerate(DBS):
                size = await check_db_size(database)
                if size < 407:
                    model = MODELS[idx]
                    cursor = model.collection.find().sort("$natural", -1).limit(limit)
                    files = await cursor.to_list(length=limit)
                    return files
        cursor = MODELS[0].collection.find().sort("$natural", -1).limit(limit)
        files = await cursor.to_list(length=limit)
        return files
    except Exception as e:
        logger.error(f"Error in fetch_media: {e}")
        return []

async def dreamxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    """Clean filename for display."""
    try:
        year_match = re.search(r"^(.*?(\d{4}|\(\d{4}\)))", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).replace("(", "").replace(")", "")
            return re.sub(
                r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)",
                " ",
                title,
            ).strip().title()
        if is_series:
            season_match = re.search(
                r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?",
                filename,
                re.IGNORECASE,
            )
            if season_match:
                title = season_match.group(1).strip()
                season = season_match.group(2) or season_match.group(3) or season_match.group(4)
                title = re.sub(
                    r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)",
                    " ",
                    title,
                ).strip().title()
                return f"{title} S{int(season):02}"
        title = filename
        return re.sub(
            r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)",
            " ",
            title,
        ).strip().title()
    except Exception as e:
        logger.error(f"Error in clean_title: {e}")
        return filename

async def dreamxbotz_get_movies(limit: int = 20) -> List[str]:
    try:
        cursor = await dreamxbotz_fetch_media(limit * 2)
        results = set()
        pattern = r"(?:s\d{1,2}|season\s*\d+|season\d+)(?:\s*combined)?(?:e\d{1,2}|episode\s*\d+)?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            if not re.search(pattern, file_name, re.IGNORECASE):
                title = await dreamxbotz_clean_title(file_name)
                results.add(title)
            if len(results) >= limit:
                break
        return sorted(list(results))[:limit]
    except Exception as e:
        logger.error(f"Error in get_movies: {e}")
        return []

async def dreamxbotz_get_series(limit: int = 30) -> Dict[str, List[int]]:
    try:
        cursor = await dreamxbotz_fetch_media(limit * 5)
        grouped = defaultdict(list)
        pattern = r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?(?:E(\d{1,2})|Episode\s*(\d+))?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            match = re.search(pattern, file_name, re.IGNORECASE)
            if match:
                title = await dreamxbotz_clean_title(match.group(1), is_series=True)
                season = int(match.group(2) or match.group(3) or match.group(4))
                grouped[title].append(season)
        return {
            title: sorted(set(seasons))[:10]
            for title, seasons in grouped.items()
            if seasons
        }
    except Exception as e:
        logger.error(f"Error in get_series: {e}")
        return []

# ============================================================
# FUTURE-PROOF: ADDITIONAL UTILITIES
# ============================================================
async def get_total_file_count() -> int:
    """Count files across all databases."""
    total = 0
    for model in MODELS:
        try:
            total += await model.collection.count_documents({})
        except Exception as e:
            logger.error(f"Count error in DB: {e}")
    return total

async def delete_file(file_id: str) -> bool:
    """Delete a file from all databases."""
    deleted = False
    for model in MODELS:
        try:
            result = await model.collection.delete_one({"_id": file_id})
            if result.deleted_count:
                deleted = True
        except Exception as e:
            logger.error(f"Delete error: {e}")
    return deleted

async def clear_all_files() -> int:
    """Delete all files from all databases (dangerous)."""
    total = 0
    for model in MODELS:
        try:
            result = await model.collection.delete_many({})
            total += result.deleted_count
        except Exception as e:
            logger.error(f"Clear error: {e}")
    return total

# ============================================================
# End of ia_filterdb.py
# ============================================================
