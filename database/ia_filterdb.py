import logging
from struct import pack
import re
import base64
from pyrogram.file_id import FileId
from typing import Dict, List
from collections import defaultdict
from pymongo.errors import DuplicateKeyError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from utils import get_settings, save_group_settings
from info import (
    COLLECTION_NAME, COVERX, DATABASE_NAME, DATABASE_URI, DATABASE_URI2, DATABASE_URI3,
    INDEX_CAPTION, MAX_B_TN, MULTIPLE_DB, ULTRA_FAST_MODE, USE_CAPTION_FILTER,
    DATABASE_URIS  # <-- list of all URIs
)
from datetime import datetime, timedelta
import asyncio
from functools import lru_cache

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Global cache for DB size
_db_stats_cache = {"timestamp": None, "primary_size": 0.0}

@lru_cache(maxsize=4096)
def compile_regex(pattern):
    return re.compile(pattern, re.IGNORECASE)

# ============================================================
# DYNAMIC DATABASE POOL (UNLIMITED)
# ============================================================
_all_clients = []
_all_dbs = []
_all_instances = []
_all_models = []

for uri in DATABASE_URIS:
    client = AsyncIOMotorClient(uri)
    db = client[DATABASE_NAME]
    instance = Instance.from_db(db)
    _all_clients.append(client)
    _all_dbs.append(db)
    _all_instances.append(instance)

def _create_model(instance):
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
            indexes = ("$file_name",)
            collection_name = COLLECTION_NAME

    instance.register(MediaModel)
    return MediaModel

# Create models and assign collection attribute
MODELS = []
COLLECTIONS = []
for db in _all_dbs:
    inst = Instance.from_db(db)
    model = _create_model(inst)
    # Explicitly set collection attribute on the model class
    model.collection = db[COLLECTION_NAME]
    MODELS.append(model)
    COLLECTIONS.append(db[COLLECTION_NAME])

# Backward compatible aliases
Media = MODELS[0] if MODELS else None
Media2 = MODELS[1] if len(MODELS) > 1 else Media
Media3 = MODELS[2] if len(MODELS) > 2 else Media2
db = _all_dbs[0]
db2 = _all_dbs[1] if len(_all_dbs) > 1 else db
db3 = _all_dbs[2] if len(_all_dbs) > 2 else db2

# Expose as lists for admin panel, etc.
DBS = _all_dbs

# ============================================================
# CHECK DB SIZE (unchanged)
# ============================================================
async def check_db_size(db):
    try:
        now = datetime.utcnow()
        cache_stale_by_time = _db_stats_cache["timestamp"] is None or (
            now - _db_stats_cache["timestamp"] > timedelta(minutes=10)
        )
        refresh_if_size_threshold = _db_stats_cache["primary_size"] >= 10.0
        if not cache_stale_by_time and not refresh_if_size_threshold:
            return _db_stats_cache["primary_size"]
        stats = await db.command("dbstats")
        db_logical_size = stats["dataSize"]
        db_index_size = stats["indexSize"]
        db_logical_size_mb = db_logical_size / (1024 * 1024)
        db_index_size_mb = db_index_size / (1024 * 1024)
        db_size_mb = db_logical_size_mb + db_index_size_mb
        _db_stats_cache["primary_size"] = db_size_mb
        _db_stats_cache["timestamp"] = now
        return db_size_mb
    except Exception:
        logger.exception("Error checking database size")
        return 0

# ============================================================
# SAVE FILE (preserved behavior, works across all DBs)
# ============================================================
async def save_file(media):
    """Save file in database, with detailed logging and dynamic selection."""
    file_id, file_ref = unpack_new_file_id(media.file_id)
    file_name = re.sub(
        r"[_\-\.#+$%^&*()!~`,;:\"'?/<>\[\]{}=|\\]", " ", str(media.file_name)
    )
    file_name = re.sub(r"\s+", " ", file_name).strip()

    # Check duplicates across ALL databases
    for idx, model in enumerate(MODELS):
        exists = await model.find_one({"file_id": file_id})
        if exists:
            logger.info(f"[SKIP] '{file_name}' already in DB{idx+1}.")
            return False, 0

    # Choose the smallest database (by size) among all DBs
    target_index = 0
    if len(DBS) > 1:
        min_size = float('inf')
        for idx, d in enumerate(DBS):
            try:
                size = await check_db_size(d)
                if size < min_size:
                    min_size = size
                    target_index = idx
            except Exception:
                continue

    target_model = MODELS[target_index]
    target_db_name = f"DB{target_index+1}"

    try:
        cover_to_use = getattr(getattr(media, "cover", None), "file_id", None)
        record = target_model(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=media.file_size,
            file_type=media.file_type,
            mime_type=media.mime_type,
            caption=(media.caption.html if media.caption and INDEX_CAPTION else None),
            cover=cover_to_use if COVERX else None,
        )
    except Exception as e:
        logger.exception(f"[ERROR] '{file_name}' → {e}")
        return False, 2

    try:
        await record.commit()
    except DuplicateKeyError:
        logger.info(f"[SKIP] DuplicateKey: '{file_name}' already exists in {target_db_name} DB.")
        return False, 0
    except Exception as e:
        logger.exception(f"[ERROR] Failed commit of '{file_name}' to {target_db_name} DB.", exc_info=e)
        return False, 3

    return True, 1

# ============================================================
# GET SEARCH RESULTS (preserved logic, searches all DBs)
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
        if USE_CAPTION_FILTER:
            filter_mongo = {"$or": [{"file_name": regex},{"caption": regex},]}
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
            raw_pattern = (r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])" )
        try:
            regex = compile_regex(raw_pattern)
        except re.error:
            return [], None, 0
        if USE_CAPTION_FILTER:
            filter_mongo = { "$or": [{"file_name": regex}, {"caption": regex},]}
        else:
            filter_mongo = {"file_name": regex}

    if file_type:
        filter_mongo["file_type"] = file_type

    if ULTRA_FAST_MODE:
        limit = max_results + 1
        fetch_limit = offset + limit
        tasks = [model.find(filter_mongo).sort("$natural", -1).limit(fetch_limit).to_list(length=fetch_limit) for model in MODELS]
        results = await asyncio.gather(*tasks)
        files = []
        for res in results:
            files.extend(res)
        files = files[offset:offset + limit]
        has_next_page = len(files) > max_results
        if has_next_page:
            files = files[:-1]
        next_offset = offset + len(files) if has_next_page else ""
        total_results = offset + len(files) + (1 if has_next_page else 0)
    else:
        fetch_limit = offset + max_results
        count_tasks = [model.count_documents(filter_mongo) for model in MODELS]
        find_tasks = [model.find(filter_mongo).sort("$natural", -1).limit(fetch_limit).to_list(length=fetch_limit) for model in MODELS]
        count_results, find_results = await asyncio.gather(
            asyncio.gather(*count_tasks),
            asyncio.gather(*find_tasks)
        )
        total_results = sum(count_results)
        files = []
        for res in find_results:
            files.extend(res)
        files = files[offset:offset + max_results]
        next_offset = offset + len(files)
        if next_offset >= total_results:
            next_offset = ""
    return files, next_offset, total_results

# ============================================================
# GET BAD FILES (preserved, searches all DBs)
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
    if USE_CAPTION_FILTER:
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]}
    else:
        filter_mongo = {"file_name": regex}
    if file_type:
        filter_mongo["file_type"] = file_type

    tasks = [model.find(filter_mongo).sort("$natural", -1).to_list(300) for model in MODELS]
    results = await asyncio.gather(*tasks)
    files = []
    for res in results:
        files.extend(res)
    files = files[:300]
    return files, len(files)

# ============================================================
# GET FILE DETAILS (preserved, searches all DBs)
# ============================================================
async def get_file_details(query):
    filter = {"file_id": query}
    tasks = [model.find(filter).to_list(length=1) for model in MODELS]
    results = await asyncio.gather(*tasks)
    for filedetails in results:
        if filedetails:
            return filedetails
    return []

# ============================================================
# ENCODE/DECODE FILE ID (unchanged)
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
# DREAMXBOTZ FETCH MEDIA (preserved, works across all DBs)
# ============================================================
async def dreamxbotz_fetch_media(limit: int) -> List[dict]:
    try:
        if len(DBS) > 1:
            for idx, d in enumerate(DBS):
                size = await check_db_size(d)
                if size < 407:
                    model = MODELS[idx]
                    cursor = model.find().sort("$natural", -1).limit(limit)
                    files = await cursor.to_list(length=limit)
                    return files
        cursor = MODELS[0].find().sort("$natural", -1).limit(limit)
        files = await cursor.to_list(length=limit)
        return files
    except Exception as e:
        logger.error(f"Error in dreamxbotz_fetch_media: {e}")
        return []

# ============================================================
# DREAMXBOTZ CLEAN TITLE (unchanged)
# ============================================================
async def dreamxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    try:
        year_match = re.search(r"^(.*?(\d{4}|\(\d{4}\)))", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).replace("(", "").replace(")", "")
            return (
                re.sub(
                    r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)",
                    " ",
                    title,
                )
                .strip()
                .title()
            )
        if is_series:
            season_match = re.search(
                r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?",
                filename,
                re.IGNORECASE,
            )
            if season_match:
                title = season_match.group(1).strip()
                season = (
                    season_match.group(2)
                    or season_match.group(3)
                    or season_match.group(4)
                )
                title = (
                    re.sub(
                        r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)",
                        " ",
                        title,
                    )
                    .strip()
                    .title()
                )
                return f"{title} S{int(season):02}"
        title = filename
        return (
            re.sub(
                r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title
            )
            .strip()
            .title()
        )
    except Exception as e:
        logger.error(f"Error in truncate_title: {e}")
        return filename

# ============================================================
# DREAMXBOTZ GET MOVIES (unchanged)
# ============================================================
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
        logger.error(f"Error in dreamxbotz_get_movies: {e}")
        return []

# ============================================================
# DREAMXBOTZ GET SERIES (unchanged)
# ============================================================
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
        logger.error(f"Error in dreamxbotz_get_series: {e}")
        return []
