import time
import logging
import asyncio
import re
import base64
from struct import pack
from typing import Dict, List, Optional, Tuple, Union, Any
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlparse

from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, PyMongoError, ConnectionFailure, OperationFailure
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from umongo import Instance, Document, fields, ValidationError

from utils import get_settings, save_group_settings
from info import (
    COLLECTION_NAME, COVERX, DATABASE_NAME, DATABASE_URI, DATABASE_URI2, DATABASE_URI3,
    INDEX_CAPTION, MAX_B_TN, MULTIPLE_DB, ULTRA_FAST_MODE, USE_CAPTION_FILTER,
    DATABASE_URIS, MEDIA_DATABASE_URIS
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_db_stats_cache = {"timestamp": None, "primary_size": 0.0}
_search_cache = {}
_SEARCH_CACHE_TTL = 60

@lru_cache(maxsize=4096)
def compile_regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)

# ============================================================
# DYNAMIC DATABASE POOL
# ============================================================
_all_clients = []
_all_dbs = []
_all_instances = []
_all_models = []
_all_labels = []
_all_uris = []

def get_db_label(uri: str) -> str:
    try:
        parsed = urlparse(uri)
        return parsed.hostname or "unknown"
    except Exception:
        return "unknown"

def _create_model(instance: Instance) -> type:
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
            try:
                if cls.collection is not None:
                    await cls.collection.create_index([("file_name", 1)])
            except Exception as e:
                logger.error(f"Index creation failed: {e}")
                try:
                    await cls.collection.create_index([("file_name", "text")])
                except Exception:
                    pass

    return instance.register(MediaModel)

def _initialize_database_pool():
    global _all_clients, _all_dbs, _all_instances, _all_models
    global _all_labels, _all_uris
    global client, client2, client3, db, db2, db3, Media, Media2, Media3
    global DBS, MODELS, COLLECTIONS, DB_LABELS, USER_DB_LABEL

    _all_clients = []
    _all_dbs = []
    _all_instances = []
    _all_models = []
    _all_labels = []
    _all_uris = []

    for uri in MEDIA_DATABASE_URIS:
        try:
            client_temp = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
            db_temp = client_temp[DATABASE_NAME]
            instance_temp = Instance.from_db(db_temp)
            _all_clients.append(client_temp)
            _all_dbs.append(db_temp)
            _all_instances.append(instance_temp)
            _all_uris.append(uri)
            _all_labels.append(get_db_label(uri))
        except Exception as e:
            logger.error(f"Failed to connect to DB at {uri}: {e}")

    if not _all_dbs:
        raise RuntimeError("No valid MongoDB connection found.")

    for db_temp in _all_dbs:
        inst_temp = Instance.from_db(db_temp)
        model = _create_model(inst_temp)
        _all_models.append(model)

    client = _all_clients[0]
    client2 = _all_clients[1] if len(_all_clients) > 1 else client
    client3 = _all_clients[2] if len(_all_clients) > 2 else client2

    db = _all_dbs[0]
    db2 = _all_dbs[1] if len(_all_dbs) > 1 else db
    db3 = _all_dbs[2] if len(_all_dbs) > 2 else db2

    Media = _all_models[0]
    Media2 = _all_models[1] if len(_all_models) > 1 else Media
    Media3 = _all_models[2] if len(_all_models) > 2 else Media2

    DBS = _all_dbs
    MODELS = _all_models
    COLLECTIONS = [db_temp[COLLECTION_NAME] for db_temp in _all_dbs]
    DB_LABELS = _all_labels
 

_initialize_database_pool()

# Add this after the function call
USER_DB_LABEL = get_db_label(DATABASE_URI) if DATABASE_URI else "unknown"
# ============================================================
# DB SIZE
# ============================================================
async def check_db_size(database):
    try:
        now = datetime.utcnow()
        cache_stale = (
            _db_stats_cache["timestamp"] is None
            or (now - _db_stats_cache["timestamp"] > timedelta(minutes=10))
        )
        force_refresh = _db_stats_cache["primary_size"] >= 10.0
        if not cache_stale and not force_refresh:
            return _db_stats_cache["primary_size"]
        stats = await database.command("dbstats")
        size_mb = (stats["dataSize"] + stats["indexSize"]) / (1024 * 1024)
        _db_stats_cache["primary_size"] = size_mb
        _db_stats_cache["timestamp"] = now
        return size_mb
    except Exception:
        return 0

# ============================================================
# SAVE FILE
# ============================================================
async def save_file(media):
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
    except Exception:
        return False, 3

    file_name = re.sub(
        r"[_\-\.#+$%^&*()!~`,;:\"'?/<>\[\]{}=|\\]", " ", str(media.file_name)
    )
    file_name = re.sub(r"\s+", " ", file_name).strip()
    if not file_name:
        file_name = "Unknown File"

    for idx, model in enumerate(MODELS):
        exists = await model.collection.find_one({"file_id": file_id})
        if exists:
            return False, 0

    target_index = 0
    if len(DBS) > 1:
        min_size = float("inf")
        for idx, database in enumerate(DBS):
            size = await check_db_size(database)
            if size < min_size:
                min_size = size
                target_index = idx

    target_model = MODELS[target_index]
    target_db_name = f"DB{target_index+1} ({DB_LABELS[target_index]})"

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
    except ValidationError:
        return False, 2
    except Exception:
        return False, 3

    try:
        await record.commit()
        return True, 1
    except DuplicateKeyError:
        return False, 0
    except OperationFailure:
        if target_index + 1 < len(MODELS):
            try:
                record2 = MODELS[target_index + 1](**record.to_mongo())
                await record2.commit()
                return True, 1
            except Exception:
                pass
        return False, 3
    except Exception:
        return False, 3

# ============================================================
# SEARCH RESULTS (using MODELS[i].find for umongo docs)
# ============================================================
async def get_search_results(chat_id, query, file_type=None, max_results=None, offset=0, filter=False):
    if chat_id is not None and max_results is None:
        settings = await get_settings(int(chat_id))
        if "max_btn" not in settings:
            await save_group_settings(int(chat_id), "max_btn", True)
            settings["max_btn"] = True
        max_results = 10 if settings["max_btn"] else int(MAX_B_TN)

    if isinstance(query, list):
        raw_pattern = "|".join(re.escape(q.strip()) for q in query if q and q.strip())
        if not raw_pattern:
            return [], None, 0
        regex = compile_regex(raw_pattern)
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}
    else:
        query = query.strip()
        if not query:
            return [], None, 0
        if " " in query:
            words = [re.escape(w) for w in query.split() if w]
            raw_pattern = r".*[\s\.\+\-_]".join(words) if words else r"."
        else:
            raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
        try:
            regex = compile_regex(raw_pattern)
        except re.error:
            return [], None, 0
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}

    if file_type:
        filter_mongo["file_type"] = file_type

    cache_key = f"{query}|{file_type}|{max_results}|{offset}|{chat_id}"
    cached = _search_cache.get(cache_key)
    if cached and (time.time() - cached[0] < _SEARCH_CACHE_TTL):
        return cached[1], cached[2], cached[3]

    try:
        if ULTRA_FAST_MODE:
            limit = max_results + 1
            fetch_limit = offset + limit
            tasks = [
                MODELS[idx].find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for idx in range(len(MODELS))
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
            count_tasks = [COLLECTIONS[idx].count_documents(filter_mongo) for idx in range(len(MODELS))]
            find_tasks = [
                MODELS[idx].find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for idx in range(len(MODELS))
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

    _search_cache[cache_key] = (time.time(), files, next_offset, total_results)
    return files, next_offset, total_results

# ============================================================
# BAD FILES (using MODELS[i].find)
# ============================================================
async def get_bad_files(query, file_type=None):
    query = query.strip()
    if not query:
        return [], 0
    if " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = r".*[\s\.\+\-_]".join(map(re.escape, query.split()))
    try:
        regex = compile_regex(raw_pattern)
    except re.error:
        return [], 0
    filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}
    if file_type:
        filter_mongo["file_type"] = file_type

    tasks = [
        MODELS[idx].find(filter_mongo).sort("$natural", -1).to_list(300)
        for idx in range(len(MODELS))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    files = []
    for res in results:
        if isinstance(res, Exception):
            continue
        files.extend(res)
    return files[:300], len(files[:300])

# ============================================================
# FILE DETAILS (using MODELS[i].find)
# ============================================================
async def get_file_details(query):
    filter = {"file_id": query}
    tasks = [
        MODELS[idx].find(filter).to_list(length=1)
        for idx in range(len(MODELS))
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        if res:
            return res
    return []

# ============================================================
# ENCODE/DECODE
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
    file_id = encode_file_id(pack("<iiqq", int(decoded.file_type), decoded.dc_id, decoded.media_id, decoded.access_hash))
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref

# ============================================================
# MEDIA HELPERS (using MODELS[idx].find)
# ============================================================
async def dreamxbotz_fetch_media(limit: int = 20):
    try:
        if len(DBS) > 1:
            for idx, database in enumerate(DBS):
                size = await check_db_size(database)
                if size < 407:
                    cursor = MODELS[idx].find().sort("$natural", -1).limit(limit)
                    return await cursor.to_list(length=limit)
        cursor = MODELS[0].find().sort("$natural", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Error in fetch_media: {e}")
        return []

async def dreamxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    # Same as before
    try:
        year_match = re.search(r"^(.*?(\d{4}|\(\d{4}\)))", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).replace("(", "").replace(")", "")
            return re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title).strip().title()
        if is_series:
            season_match = re.search(r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?", filename, re.IGNORECASE)
            if season_match:
                title = season_match.group(1).strip()
                season = season_match.group(2) or season_match.group(3) or season_match.group(4)
                title = re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title).strip().title()
                return f"{title} S{int(season):02}"
        return re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", filename).strip().title()
    except Exception as e:
        return filename

async def dreamxbotz_get_movies(limit: int = 20):
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
        return []

async def dreamxbotz_get_series(limit: int = 30):
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
        return {title: sorted(set(seasons))[:10] for title, seasons in grouped.items() if seasons}
    except Exception as e:
        return []

# ============================================================
# EXTRA UTILITIES
# ============================================================
async def get_total_file_count() -> int:
    total = 0
    for col in COLLECTIONS:
        try:
            total += await col.count_documents({})
        except Exception:
            pass
    return total

async def delete_file(file_id: str) -> bool:
    deleted = False
    for col in COLLECTIONS:
        try:
            result = await col.delete_one({"_id": file_id})
            if result.deleted_count:
                deleted = True
        except Exception:
            pass
    return deleted

async def clear_all_files() -> int:
    total = 0
    for col in COLLECTIONS:
        try:
            result = await col.delete_many({})
            total += result.deleted_count
        except Exception:
            pass
    return total

# ============================================================
# END
# ============================================================
