# ============================================================
# DOWNTOWN VILLA — ULTIMATE BACKUP PLUGIN (DYNAMIC DBs)
# ============================================================
#
# ONE ADMIN COMMAND:
#
#     /backup
#
# FEATURES
# ------------------------------------------------------------
# • Automatically detects all media databases (DBS/DB_LABELS)
# • Shows each database by its cluster name (e.g., DATA-BASE-02)
# • Auto‑includes new databases without code changes
# • Live task tracking (shows in admin panel's 🚀 TASKS page)
# • Colorful emoji progress bar
# • Resumes from last uploaded file (persistent state)
# • Pause / Resume / Stop / Retry Failed
# • Uses original file metadata as caption
# • Shows current database and file
# • FloodWait handling
# • Exponential retry delay
# • Admin-only access
#
# REQUIRED ENVIRONMENT
# ------------------------------------------------------------
#
# BACKUP_CHANNEL_ID=-100xxxxxxxxxxxx
#
# OPTIONAL
#
# BACKUP_AUTO_START=true
# BACKUP_WATCH_INTERVAL=5
# BACKUP_UPLOAD_DELAY=0.5
# BACKUP_RETRY_DELAY=5
# BACKUP_MAX_RETRIES=8
# BACKUP_RECONCILE_MESSAGES=1000
# BACKUP_STATE_COLLECTION=<auto generated>
# BACKUP_RUN_COLLECTION=<auto generated>
#
# ============================================================

import os
import time
import asyncio
import hashlib
import logging
import traceback
import importlib
from datetime import datetime, timedelta
from collections import defaultdict

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import (
    FloodWait,
    RPCError,
)

from database.ia_filterdb import (
    DBS,          # list of media databases
    COLLECTIONS,  # list of media collections
    DB_LABELS,    # human-readable cluster labels (e.g., "DATA-BASE-02")
)

try:
    from info import (
        ADMINS,
        COLLECTION_NAME,
        MULTIPLE_DB,
    )
except Exception:
    ADMINS = []
    COLLECTION_NAME = "Telegram_files"
    MULTIPLE_DB = True

# Import admin panel functions dynamically (because filename has a hyphen)
admin_panel = importlib.import_module("plugins.admin_panel_ultimate-2")
start_live_task = admin_panel.start_live_task
update_live_task = admin_panel.update_live_task
finish_live_task = admin_panel.finish_live_task

# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# CONFIGURATION
# ============================================================

BACKUP_CHANNEL_ID_RAW = os.getenv(
    "BACKUP_CHANNEL_ID",
    "",
).strip()

BACKUP_AUTO_START = os.getenv(
    "BACKUP_AUTO_START",
    "true",
).lower() in {
    "true",
    "1",
    "yes",
    "on",
}

BACKUP_WATCH_INTERVAL = max(
    2,
    int(
        os.getenv(
            "BACKUP_WATCH_INTERVAL",
            "5",
        )
    ),
)

BACKUP_UPLOAD_DELAY = max(
    0.0,
    float(
        os.getenv(
            "BACKUP_UPLOAD_DELAY",
            "0.5",
        )
    ),
)

BACKUP_RETRY_DELAY = max(
    1,
    int(
        os.getenv(
            "BACKUP_RETRY_DELAY",
            "5",
        )
    ),
)

BACKUP_MAX_RETRIES = max(
    1,
    int(
        os.getenv(
            "BACKUP_MAX_RETRIES",
            "8",
        )
    ),
)

BACKUP_RECONCILE_MESSAGES = max(
    100,
    int(
        os.getenv(
            "BACKUP_RECONCILE_MESSAGES",
            "1000",
        )
    ),
)

BACKUP_STATE_COLLECTION = os.getenv(
    "BACKUP_STATE_COLLECTION",
    f"{COLLECTION_NAME}_backup_state",
)

BACKUP_RUN_COLLECTION = os.getenv(
    "BACKUP_RUN_COLLECTION",
    f"{COLLECTION_NAME}_backup_runs",
)

BACKUP_TOKEN_PREFIX = os.getenv(
    "BACKUP_TOKEN_PREFIX",
    "DTV-BACKUP",
)

# ============================================================
# ADMIN PARSING
# ============================================================

def _build_admin_set():
    result = set()

    values = ADMINS

    if isinstance(values, (str, int)):
        values = str(values).replace(",", " ").split()

    if values is None:
        values = []

    try:
        for value in values:
            try:
                result.add(int(value))
            except Exception:
                pass
    except Exception:
        pass

    env_admins = os.getenv(
        "ADMINS",
        "",
    ).replace(",", " ").split()

    for value in env_admins:
        try:
            result.add(int(value))
        except Exception:
            pass

    return result

ADMIN_IDS = _build_admin_set()

def is_admin(user_id):
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False

# ============================================================
# CHANNEL
# ============================================================

def get_backup_channel_id():
    if not BACKUP_CHANNEL_ID_RAW:
        return None

    try:
        return int(
            BACKUP_CHANNEL_ID_RAW
        )
    except Exception:
        return None

def backup_configured():
    return get_backup_channel_id() is not None

# ============================================================
# DYNAMIC SOURCE DATABASES
# ============================================================

# Build source databases dynamically from the media pool
SOURCE_DATABASES = []
for index, (database, label) in enumerate(zip(DBS, DB_LABELS), start=1):
    SOURCE_DATABASES.append(
        (
            label,
            database,
            index,
        )
    )

# Fallback if DBS empty (shouldn't happen)
if not SOURCE_DATABASES:
    SOURCE_DATABASES = [
        ("DATA-BASE-01", None, 1),
    ]

def enabled_source_databases():
    # If MULTIPLE_DB is False, use only first DB, else all
    if MULTIPLE_DB:
        return SOURCE_DATABASES
    return SOURCE_DATABASES[:1]

def source_collection(database):
    if database is None:
        return None

    return database[
        COLLECTION_NAME
    ]

# ============================================================
# STATE COLLECTION
# ============================================================

def state_collection():
    if DBS and DBS[0] is not None:
        return DBS[0][
            BACKUP_STATE_COLLECTION
        ]
    return None

def run_collection():
    if DBS and DBS[0] is not None:
        return DBS[0][
            BACKUP_RUN_COLLECTION
        ]
    return None

# ============================================================
# RUNTIME STATE
# ============================================================

STATE = {
    "running": False,
    "paused": False,
    "stop_requested": False,
    "mode": "IDLE",

    "started_at": None,
    "finished_at": None,

    "current_db": None,
    "current_db_number": 0,

    "current_file": None,
    "current_file_id": None,
    "current_file_size": 0,

    "current_source_index": 0,
    "current_source_total": 0,

    "current_uploaded": 0,
    "current_failed": 0,
    "current_skipped": 0,

    "total_uploaded": 0,
    "total_failed": 0,
    "total_skipped": 0,

    "speed": 0.0,
    "eta": None,

    "last_error": None,
    "last_activity": None,
    "last_success": None,
    "last_message_id": None,

    "last_cycle": 0,
    "last_scan": None,

    "run_id": None,

    "message": "",
    "worker_pid": os.getpid(),

    "live_task_id": None,   # For admin panel TASKS page
}

WORKER_TASK = None
WATCHER_TASK = None

STATE_LOCK = asyncio.Lock()
PANEL_LOCK = asyncio.Lock()

ACTIVE_PANELS = {}

# ============================================================
# HELPERS
# ============================================================

def now():
    return datetime.utcnow()

def now_text():
    return now().strftime(
        "%d %b %Y • %H:%M:%S UTC"
    )

def fmt_int(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"

def fmt_float(value, places=2):
    try:
        return f"{float(value):.{places}f}"
    except Exception:
        return f"{0:.{places}f}"

def fmt_bytes(value):
    try:
        value = float(value)
    except Exception:
        return "0 B"

    if value <= 0:
        return "0 B"

    units = (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
        "PB",
        "EB",
    )

    index = 0

    while (
        value >= 1024
        and index < len(units) - 1
    ):
        value /= 1024
        index += 1

    return (
        f"{value:.2f} "
        f"{units[index]}"
    )

def fmt_duration(seconds):
    if seconds is None:
        return "0s"

    try:
        seconds = max(
            0,
            int(seconds),
        )
    except Exception:
        return "0s"

    days, seconds = divmod(
        seconds,
        86400,
    )

    hours, seconds = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        seconds,
        60,
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if seconds or not parts:
        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts)

def html_escape(value):
    text = str(
        value
        if value is not None
        else ""
    )

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def short(value, length=90):
    text = str(
        value
        if value is not None
        else "-"
    )

    if len(text) <= length:
        return text

    return text[: length - 3] + "..."

def progress_bar(
    current,
    total,
    length=20,
):
    """
    Colorful emoji progress bar.
    """
    try:
        current = float(current)
        total = float(total)
    except Exception:
        current = 0
        total = 0

    if total <= 0:
        percent = 0
    else:
        percent = (
            current / total
        ) * 100

    percent = max(
        0,
        min(
            100,
            percent,
        ),
    )

    filled = int(
        length
        * percent
        / 100
    )

    if filled >= length:
        bar = "🟩" * length
    else:
        bar = "🟩" * filled + "🟨" + "⬜" * (length - filled - 1)

    return f"{bar} {percent:.1f}%"

def status_icon(status):
    status = str(
        status or ""
    ).upper()

    if status in {
        "ONLINE",
        "RUNNING",
        "UPLOADED",
        "COMPLETED",
        "CONNECTED",
        "ACTIVE",
    }:
        return "🟢"

    if status in {
        "FAILED",
        "ERROR",
        "OFFLINE",
        "STOPPED",
    }:
        return "🔴"

    if status in {
        "PAUSED",
        "WAITING",
        "PENDING",
        "UPLOADING",
        "RECONCILING",
    }:
        return "🟡"

    return "⚪"

# ============================================================
# SOURCE FILE HELPERS
# ============================================================

def source_file_id(document):
    value = document.get(
        "_id"
    )

    if value is None:
        value = document.get(
            "file_id"
        )

    if value is None:
        return None

    return str(value)

def source_file_name(document):
    value = document.get(
        "file_name"
    )

    if value:
        return str(value)

    return "Unknown File"

def source_file_size(document):
    try:
        return int(
            document.get(
                "file_size",
                0,
            )
            or 0
        )
    except Exception:
        return 0

def source_caption(document):
    value = document.get(
        "caption"
    )

    if value:
        return str(value)

    return source_file_name(
        document
    )

def backup_key(
    source_db,
    file_id,
):
    return (
        f"{source_db}:"
        f"{file_id}"
    )

def backup_token(
    source_db,
    file_id,
):
    raw = (
        f"{BACKUP_TOKEN_PREFIX}|"
        f"{source_db}|"
        f"{file_id}"
    ).encode(
        "utf-8"
    )

    digest = hashlib.sha256(
        raw
    ).hexdigest()

    return (
        f"{BACKUP_TOKEN_PREFIX}-"
        f"{source_db}-"
        f"{digest[:32]}"
    )

# ============================================================
# INDEXES
# ============================================================

async def ensure_indexes():
    collection = state_collection()

    if collection is None:
        return False

    try:
        await collection.create_index(
            [
                (
                    "source_db",
                    1,
                ),
                (
                    "file_id",
                    1,
                ),
            ],
            unique=True,
            name="source_file_unique",
        )

        await collection.create_index(
            [
                (
                    "source_db",
                    1,
                ),
                (
                    "status",
                    1,
                ),
            ],
            name="source_status",
        )

        await collection.create_index(
            [
                (
                    "status",
                    1,
                ),
                (
                    "updated_at",
                    1,
                ),
            ],
            name="status_updated",
        )

        await collection.create_index(
            [
                (
                    "backup_token",
                    1,
                ),
            ],
            unique=True,
            sparse=True,
            name="backup_token_unique",
        )

        runs = run_collection()

        if runs is not None:
            await runs.create_index(
                [
                    (
                        "started_at",
                        -1,
                    ),
                ],
                name="runs_started",
            )

        return True

    except Exception:
        logger.exception(
            "Backup index creation failed"
        )
        return False

# ============================================================
# STATE STORAGE
# ============================================================

async def get_state(
    source_db,
    file_id,
):
    collection = state_collection()

    if collection is None:
        return None

    try:
        return await collection.find_one(
            {
                "source_db": source_db,
                "file_id": str(file_id),
            }
        )
    except Exception:
        logger.exception(
            "Backup state read failed"
        )
        return None

async def get_status(
    source_db,
    file_id,
):
    record = await get_state(
        source_db,
        file_id,
    )

    if not record:
        return "PENDING"

    return str(
        record.get(
            "status",
            "PENDING",
        )
    ).upper()

async def set_state(
    source_db,
    document,
    status,
    *,
    message_id=None,
    error=None,
    attempts=None,
):
    collection = state_collection()

    if collection is None:
        raise RuntimeError(
            "Backup state collection unavailable"
        )

    file_id = source_file_id(
        document
    )

    if not file_id:
        raise ValueError(
            "Document has no file_id"
        )

    token = backup_token(
        source_db,
        file_id,
    )

    timestamp = now()

    update = {
        "$set": {
            "source_db": source_db,
            "file_id": file_id,
            "file_name": source_file_name(
                document
            ),
            "file_size": source_file_size(
                document
            ),
            "backup_token": token,
            "status": str(
                status
            ).upper(),
            "updated_at": timestamp,
        },
        "$setOnInsert": {
            "created_at": timestamp,
        },
    }

    if message_id is not None:
        update["$set"][
            "message_id"
        ] = int(message_id)

    if error is not None:
        update["$set"][
            "last_error"
        ] = str(error)[:4000]

    if attempts is not None:
        update["$set"][
            "attempts"
        ] = int(attempts)

    await collection.update_one(
        {
            "source_db": source_db,
            "file_id": file_id,
        },
        update,
        upsert=True,
    )

async def mark_uploading(
    source_db,
    document,
):
    file_id = source_file_id(
        document
    )

    existing = await get_state(
        source_db,
        file_id,
    )

    attempts = (
        int(
            existing.get(
                "attempts",
                0,
            )
        )
        if existing
        else 0
    )

    await set_state(
        source_db,
        document,
        "UPLOADING",
        attempts=attempts + 1,
    )

async def mark_uploaded(
    source_db,
    document,
    message_id,
):
    await set_state(
        source_db,
        document,
        "UPLOADED",
        message_id=message_id,
    )

async def mark_failed(
    source_db,
    document,
    error,
):
    existing = await get_state(
        source_db,
        source_file_id(
            document
        ),
    )

    attempts = (
        int(
            existing.get(
                "attempts",
                0,
            )
        )
        if existing
        else 1
    )

    await set_state(
        source_db,
        document,
        "FAILED",
        error=error,
        attempts=attempts,
    )

async def reset_failed():
    collection = state_collection()

    if collection is None:
        return 0

    result = await collection.update_many(
        {
            "status": "FAILED",
        },
        {
            "$set": {
                "status": "PENDING",
                "updated_at": now(),
            }
        },
    )

    return result.modified_count


# ============================================================
# RUN RESET
# ============================================================
    
async def reset_all_state():
    """
    Clears ALL backup state records, making every file pending again.
    Use this if you want to re-upload everything to a new channel.
    """
    collection = state_collection()
    if collection is None:
        return 0

    # Option A: Delete all records (completely fresh start)
    result = await collection.delete_many({})
    return result.deleted_count

    # Option B: Set all statuses back to PENDING (keeps metadata)
    # result = await collection.update_many({}, {"$set": {"status": "PENDING", "updated_at": now()}})
    # return result.modified_count
# ============================================================
# RUN HISTORY
# ============================================================

async def create_run():
    collection = run_collection()

    if collection is None:
        return None

    result = await collection.insert_one(
        {
            "started_at": now(),
            "status": "RUNNING",
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "pid": os.getpid(),
        }
    )

    return result.inserted_id

async def finish_run(
    status,
):
    collection = run_collection()

    run_id = STATE.get(
        "run_id"
    )

    if collection is None or run_id is None:
        return

    await collection.update_one(
        {
            "_id": run_id,
        },
        {
            "$set": {
                "status": status,
                "finished_at": now(),
                "uploaded": STATE[
                    "total_uploaded"
                ],
                "failed": STATE[
                    "total_failed"
                ],
                "skipped": STATE[
                    "total_skipped"
                ],
                "last_error": STATE[
                    "last_error"
                ],
            }
        },
    )

async def get_history(
    limit=12,
):
    collection = run_collection()

    if collection is None:
        return []

    cursor = collection.find(
        {}
    ).sort(
        "started_at",
        -1,
    ).limit(
        int(limit)
    )

    return await cursor.to_list(
        length=int(limit)
    )

# ============================================================
# COUNTS
# ============================================================

async def count_state(
    source_db=None,
    status=None,
):
    collection = state_collection()

    if collection is None:
        return 0

    query = {}

    if source_db:
        query[
            "source_db"
        ] = source_db

    if status:
        query[
            "status"
        ] = str(
            status
        ).upper()

    try:
        return await collection.count_documents(
            query
        )
    except Exception:
        return 0

async def source_count(
    source_db,
    database,
):
    collection = source_collection(
        database
    )

    if collection is None:
        return 0

    try:
        return await collection.count_documents(
            {}
        )
    except Exception:
        return 0

async def database_snapshot():
    snapshot = {}

    for (
        source_db,
        database,
        number,
    ) in enabled_source_databases():

        total = await source_count(
            source_db,
            database,
        )

        uploaded = await count_state(
            source_db,
            "UPLOADED",
        )

        uploading = await count_state(
            source_db,
            "UPLOADING",
        )

        failed = await count_state(
            source_db,
            "FAILED",
        )

        pending = max(
            0,
            total - uploaded,
        )

        snapshot[
            source_db
        ] = {
            "number": number,
            "total": total,
            "uploaded": uploaded,
            "pending": pending,
            "uploading": uploading,
            "failed": failed,
        }

    return snapshot

async def total_pending():
    snapshot = await database_snapshot()

    return sum(
        item["pending"]
        for item in snapshot.values()
    )

# ============================================================
# PERSISTENT RESUME SCANNER
# ============================================================

async def pending_documents(
    database,
    source_db,
):
    source = source_collection(
        database
    )

    if source is None:
        return

    state = state_collection()

    cursor = source.find(
        {}
    ).sort(
        "$natural",
        1,
    ).batch_size(
        100,
    )

    batch = []

    async for document in cursor:
        batch.append(
            document
        )

        if len(batch) >= 100:
            async for item in pending_batch(
                batch,
                source_db,
                state,
            ):
                yield item

            batch = []

    if batch:
        async for item in pending_batch(
            batch,
            source_db,
            state,
        ):
            yield item

async def pending_batch(
    documents,
    source_db,
    state,
):
    ids = []

    for document in documents:
        file_id = source_file_id(
            document
        )

        if file_id:
            ids.append(
                file_id
            )

    if not ids:
        return

    uploaded = set()

    if state is not None:
        cursor = state.find(
            {
                "source_db": source_db,
                "file_id": {
                    "$in": ids,
                },
                "status": "UPLOADED",
            },
            {
                "file_id": 1,
                "_id": 0,
            },
        )

        async for record in cursor:
            value = record.get(
                "file_id"
            )

            if value:
                uploaded.add(
                    str(value)
                )

    for document in documents:
        file_id = source_file_id(
            document
        )

        if not file_id:
            yield document
            continue

        if file_id not in uploaded:
            yield document

# ============================================================
# CRASH RECONCILIATION
# ============================================================

async def uploading_records(
    limit=2000,
):
    collection = state_collection()

    if collection is None:
        return []

    cursor = collection.find(
        {
            "status": "UPLOADING",
        }
    ).sort(
        "updated_at",
        1,
    ).limit(
        int(limit)
    )

    return await cursor.to_list(
        length=int(limit)
    )

async def find_source_document(
    source_db,
    file_id,
):
    for (
        name,
        database,
        number,
    ) in enabled_source_databases():

        if name != source_db:
            continue

        collection = source_collection(
            database
        )

        if collection is None:
            return None

        try:
            result = await collection.find_one(
                {
                    "_id": file_id,
                }
            )

            if result is not None:
                return result

            return await collection.find_one(
                {
                    "_id": str(file_id),
                }
            )

        except Exception:
            return None

    return None

def message_has_token(
    message,
    token,
):
    if message is None:
        return False

    caption = getattr(
        message,
        "caption",
        None,
    )

    text = getattr(
        message,
        "text",
        None,
    )

    combined = (
        f"{caption or ''}\n"
        f"{text or ''}"
    )

    return token in combined

async def reconcile_one(
    app,
    record,
):
    token = record.get(
        "backup_token"
    )

    if not token:
        return False

    channel = get_backup_channel_id()

    if channel is None:
        return False

    try:
        async for message in app.get_chat_history(
            channel,
            limit=BACKUP_RECONCILE_MESSAGES,
        ):
            if message_has_token(
                message,
                token,
            ):
                source_db = record.get(
                    "source_db"
                )

                file_id = record.get(
                    "file_id"
                )

                document = await find_source_document(
                    source_db,
                    file_id,
                )

                if document is None:
                    return False

                await mark_uploaded(
                    source_db,
                    document,
                    message.id,
                )

                STATE[
                    "last_message_id"
                ] = message.id

                STATE[
                    "last_success"
                ] = now_text()

                logger.info(
                    "[BACKUP][RECONCILE] %s/%s -> message %s",
                    source_db,
                    file_id,
                    message.id,
                )

                return True

    except FloodWait as exc:
        await asyncio.sleep(
            int(
                getattr(
                    exc,
                    "value",
                    30,
                )
            )
            + 2
        )

    except Exception:
        logger.exception(
            "Reconciliation failed"
        )

    return False

async def reconcile_interrupted():
    if not backup_configured():
        return 0

    records = await uploading_records()

    if not records:
        return 0

    STATE[
        "mode"
    ] = "RECONCILING"

    STATE[
        "message"
    ] = (
        f"Checking {len(records):,} interrupted uploads"
    )

    recovered = 0

    app = STATE.get(
        "_client"
    )

    if app is None:
        return 0

    for record in records:
        if STATE[
            "stop_requested"
        ]:
            break

        if await reconcile_one(
            app,
            record,
        ):
            recovered += 1

    return recovered

# ============================================================
# BACKUP CAPTION
# ============================================================

def make_caption(
    source_db,
    document,
):
    token = backup_token(
        source_db,
        source_file_id(
            document
        ),
    )

    original = source_caption(
        document
    )

    return (
        f"{original}\n\n"
        f"🗄️ <b>DOWNTOWN VILLA BACKUP</b>\n"
        f"📚 <b>DATABASE:</b> {source_db}\n"
        f"🔐 <code>{token}</code>"
    )

# ============================================================
# TELEGRAM UPLOAD
# ============================================================

async def upload_one(
    app,
    source_db,
    document,
):
    file_id = source_file_id(
        document
    )

    file_name = source_file_name(
        document
    )

    if not file_id:
        await mark_failed(
            source_db,
            document,
            "Missing file_id",
        )

        return False

    STATE[
        "current_file"
    ] = file_name

    STATE[
        "current_file_id"
    ] = file_id

    STATE[
        "current_file_size"
    ] = source_file_size(
        document
    )

    token = backup_token(
        source_db,
        file_id,
    )

    STATE[
        "message"
    ] = (
        f"Uploading {file_name}"
    )

    await mark_uploading(
        source_db,
        document,
    )

    caption = make_caption(
        source_db,
        document,
    )

    attempts = 0

    while attempts < BACKUP_MAX_RETRIES:
        attempts += 1

        if STATE[
            "stop_requested"
        ]:
            return False

        try:
            STATE[
                "mode"
            ] = "UPLOADING"

            sent = await app.send_cached_media(
                chat_id=get_backup_channel_id(),
                file_id=file_id,
                caption=caption,
            )

            message_id = getattr(
                sent,
                "id",
                None,
            )

            if not message_id:
                raise RuntimeError(
                    "Telegram returned no message ID"
                )

            await mark_uploaded(
                source_db,
                document,
                message_id,
            )

            STATE[
                "last_message_id"
            ] = message_id

            STATE[
                "last_success"
            ] = now_text()

            STATE[
                "last_activity"
            ] = now_text()

            STATE[
                "message"
            ] = (
                f"Uploaded: {file_name}"
            )

            logger.info(
                "[BACKUP][SUCCESS] %s | %s | message=%s",
                source_db,
                file_name,
                message_id,
            )

            return True

        except FloodWait as exc:
            wait = max(
                1,
                int(
                    getattr(
                        exc,
                        "value",
                        30,
                    )
                ),
            )

            STATE[
                "mode"
            ] = "FLOOD_WAIT"

            STATE[
                "message"
            ] = (
                f"Telegram FloodWait: "
                f"{wait}s"
            )

            logger.warning(
                "[BACKUP] FloodWait %ss",
                wait,
            )

            await asyncio.sleep(
                wait + 2
            )

        except RPCError as exc:
            error = str(exc)

            STATE[
                "last_error"
            ] = error

            logger.error(
                "[BACKUP][RPC] %s",
                error,
            )

            if attempts >= BACKUP_MAX_RETRIES:
                await mark_failed(
                    source_db,
                    document,
                    error,
                )

                return False

            await asyncio.sleep(
                BACKUP_RETRY_DELAY
                * min(
                    attempts,
                    6,
                )
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            error = str(exc)

            STATE[
                "last_error"
            ] = error

            logger.error(
                "[BACKUP][ERROR] %s",
                error,
            )

            if attempts >= BACKUP_MAX_RETRIES:
                await mark_failed(
                    source_db,
                    document,
                    error,
                )

                return False

            await asyncio.sleep(
                BACKUP_RETRY_DELAY
                * min(
                    attempts,
                    6,
                )
            )

    return False

# ============================================================
# SINGLE DATABASE PASS
# ============================================================

async def backup_database(
    app,
    source_db,
    database,
    number,
):
    source = source_collection(
        database
    )

    if source is None:
        STATE[
            "last_error"
        ] = (
            f"{source_db} unavailable"
        )
        return False

    total = await source.count_documents(
        {}
    )

    already_uploaded = await count_state(
        source_db,
        "UPLOADED",
    )

    STATE[
        "current_db"
    ] = source_db

    STATE[
        "current_db_number"
    ] = number

    STATE[
        "current_source_total"
    ] = total

    STATE[
        "current_source_index"
    ] = 0

    STATE[
        "current_uploaded"
    ] = 0

    STATE[
        "current_failed"
    ] = 0

    STATE[
        "current_skipped"
    ] = already_uploaded

    STATE[
        "message"
    ] = (
        f"{source_db}: "
        f"{fmt_int(total)} source files"
    )

    logger.info(
        "[BACKUP] START %s total=%s already_uploaded=%s",
        source_db,
        total,
        already_uploaded,
    )

    # Update live task with initial DB progress
    if STATE.get("live_task_id"):
        update_live_task(
            STATE["live_task_id"],
            current=STATE["current_skipped"],
            total=total,
            message=f"Backing up {source_db}",
        )

    if total == 0:
        return True

    start_time = time.monotonic()

    async for document in pending_documents(
        database,
        source_db,
    ):
        if STATE[
            "stop_requested"
        ]:
            STATE[
                "mode"
            ] = "STOPPING"

            return False

        while STATE[
            "paused"
        ]:
            STATE[
                "mode"
            ] = "PAUSED"

            STATE[
                "message"
            ] = "Backup paused"

            await asyncio.sleep(
                1
            )

            if STATE[
                "stop_requested"
            ]:
                return False

        STATE[
            "mode"
        ] = "UPLOADING"

        STATE[
            "current_source_index"
        ] += 1

        file_id = source_file_id(
            document
        )

        status = await get_status(
            source_db,
            file_id,
        )

        if status == "UPLOADED":
            STATE[
                "current_skipped"
            ] += 1

            STATE[
                "total_skipped"
            ] += 1

            continue

        success = await upload_one(
            app,
            source_db,
            document,
        )

        if success:
            STATE[
                "current_uploaded"
            ] += 1

            STATE[
                "total_uploaded"
            ] += 1

        else:
            STATE[
                "current_failed"
            ] += 1

            STATE[
                "total_failed"
            ] += 1

        processed = (
            STATE[
                "current_uploaded"
            ]
            + STATE[
                "current_failed"
            ]
            + STATE[
                "current_skipped"
            ]
        )

        elapsed = max(
            0.001,
            time.monotonic()
            - start_time,
        )

        STATE[
            "speed"
        ] = (
            processed / elapsed
        )

        remaining = max(
            0,
            total
            - already_uploaded
            - processed,
        )

        if STATE[
            "speed"
        ] > 0:
            STATE[
                "eta"
            ] = (
                remaining
                / STATE[
                    "speed"
                ]
            )

        STATE[
            "last_activity"
        ] = now_text()

        # Update live task progress
        if STATE.get("live_task_id"):
            update_live_task(
                STATE["live_task_id"],
                current=STATE["current_uploaded"] + STATE["current_failed"] + STATE["current_skipped"],
                total=total,
                message=f"Uploaded: {STATE['current_uploaded']} | Failed: {STATE['current_failed']} | Skipped: {STATE['current_skipped']} | DB: {source_db}",
                speed=STATE["speed"],
            )

        if BACKUP_UPLOAD_DELAY > 0:
            await asyncio.sleep(
                BACKUP_UPLOAD_DELAY
            )

    return True

# ============================================================
# FULL ORDERED BACKUP
# ============================================================

async def run_backup(
    app,
    retry_failed=False,
):
    global WORKER_TASK

    async with STATE_LOCK:
        if STATE[
            "running"
        ]:
            return False

        STATE[
            "running"
        ] = True

        STATE[
            "paused"
        ] = False

        STATE[
            "stop_requested"
        ] = False

        STATE[
            "mode"
        ] = "STARTING"

        STATE[
            "started_at"
        ] = now()

        STATE[
            "finished_at"
        ] = None

        STATE[
            "last_error"
        ] = None

        STATE[
            "total_uploaded"
        ] = 0

        STATE[
            "total_failed"
        ] = 0

        STATE[
            "total_skipped"
        ] = 0

        STATE[
            "speed"
        ] = 0

        STATE[
            "eta"
        ] = None

        STATE[
            "run_id"
        ] = None

        STATE[
            "_client"
        ] = app

    if not backup_configured():
        STATE[
            "mode"
        ] = "ERROR"

        STATE[
            "last_error"
        ] = (
            "BACKUP_CHANNEL_ID is missing"
        )

        STATE[
            "running"
        ] = False

        return False

    # Start live task
    try:
        pending_count = await total_pending()   # renamed to avoid conflict
        task_id = f"backup_{int(time.time())}"
        start_live_task(
            task_id,
            name="Media Backup",
            task_type="BACKUP",
            total=pending_count,
            
        )
        STATE["live_task_id"] = task_id
        logger.info(f"Live task started: {task_id}")
    except Exception as e:
        logger.error(f"Failed to start live task: {e}")
        STATE["live_task_id"] = None

    success = False

    try:
        await ensure_indexes()

        if retry_failed:
            await reset_failed()

        # FIRST: RECONCILE CRASHED UPLOADS
        await reconcile_interrupted()

        STATE[
            "mode"
        ] = "RUNNING"

        STATE[
            "run_id"
        ] = await create_run()

        logger.info(
            "================================================"
        )

        logger.info(
            "[BACKUP] RESUMABLE BACKUP STARTED"
        )

        logger.info(
            "[BACKUP] ORDER: AUTO-DETECTED MEDIA DATABASES"
        )

        logger.info(
            "================================================"
        )

        success = True

        # LOOP THROUGH ALL MEDIA DATABASES
        for (
            source_db,
            database,
            number,
        ) in enabled_source_databases():

            if STATE[
                "stop_requested"
            ]:
                success = False
                break

            success = await backup_database(
                app,
                source_db,
                database,
                number,
            )

            if not success:
                break

        if STATE[
            "stop_requested"
        ]:
            STATE[
                "mode"
            ] = "STOPPED"

            await finish_run(
                "STOPPED"
            )

            return False

        if success:
            STATE[
                "mode"
            ] = "COMPLETED"

            STATE[
                "message"
            ] = (
                "All media databases completed"
            )

            await finish_run(
                "COMPLETED"
            )

            return True

        STATE[
            "mode"
        ] = "FAILED"

        await finish_run(
            "FAILED"
        )

        return False

    except asyncio.CancelledError:
        STATE[
            "mode"
        ] = "CANCELLED"

        try:
            await finish_run(
                "CANCELLED"
            )
        except Exception:
            pass

        raise

    except Exception as exc:
        STATE[
            "mode"
        ] = "ERROR"

        STATE[
            "last_error"
        ] = str(exc)

        logger.error(
            "[BACKUP] Worker crashed:\n%s",
            traceback.format_exc(),
        )

        try:
            await finish_run(
                "ERROR"
            )
        except Exception:
            pass

        return False

    finally:
        STATE[
            "finished_at"
        ] = now()

        # Finish live task
        if STATE.get("live_task_id"):
            try:
                if success:
                    finish_live_task(STATE["live_task_id"], "COMPLETED")
                else:
                    finish_live_task(STATE["live_task_id"], "FAILED")
            except Exception:
                pass
        # Remove the task id after finishing
        STATE["live_task_id"] = None

        STATE[
            "running"
        ] = False

        STATE[
            "paused"
        ] = False

        STATE[
            "stop_requested"
        ] = False

        STATE.pop(
            "_client",
            None,
        )

# ============================================================
# NEW FILE WATCHER
# ============================================================

async def watcher_loop(
    app,
):
    while True:
        try:
            STATE[
                "last_scan"
            ] = now_text()

            if not backup_configured():
                STATE[
                    "mode"
                ] = "NOT_CONFIGURED"

                await asyncio.sleep(
                    BACKUP_WATCH_INTERVAL
                )

                continue

            if not STATE[
                "running"
            ]:
                pending = await total_pending()

                if pending > 0:
                    await start_backup(
                        app
                    )

                else:
                    STATE[
                        "mode"
                    ] = "WATCHING"

                    STATE[
                        "message"
                    ] = (
                        "Watching for newly indexed files"
                    )

            await asyncio.sleep(
                BACKUP_WATCH_INTERVAL
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            STATE[
                "last_error"
            ] = str(exc)

            logger.error(
                "[BACKUP] Watcher error: %s",
                exc,
            )

            await asyncio.sleep(
                BACKUP_WATCH_INTERVAL
            )

def ensure_watcher(
    app,
):
    global WATCHER_TASK

    if (
        WATCHER_TASK is None
        or WATCHER_TASK.done()
    ):
        WATCHER_TASK = asyncio.create_task(
            watcher_loop(
                app
            )
        )

# ============================================================
# CONTROL
# ============================================================

async def start_backup(
    app,
):
    global WORKER_TASK

    if (
        WORKER_TASK is None
        or WORKER_TASK.done()
    ):
        WORKER_TASK = asyncio.create_task(
            run_backup(
                app,
                retry_failed=False,
            )
        )

        return True

    return False

async def retry_failed_files(
    app,
):
    global WORKER_TASK

    if (
        WORKER_TASK is None
        or WORKER_TASK.done()
    ):
        WORKER_TASK = asyncio.create_task(
            run_backup(
                app,
                retry_failed=True,
            )
        )

        return True

    return False

def pause_backup():
    if STATE[
        "running"
    ]:
        STATE[
            "paused"
        ] = True

        STATE[
            "message"
        ] = "Pause requested"

        return True

    return False

def resume_backup():
    if STATE[
        "paused"
    ]:
        STATE[
            "paused"
        ] = False

        STATE[
            "mode"
        ] = "RUNNING"

        STATE[
            "message"
        ] = "Backup resumed"

        return True

    return False

def stop_backup():
    if STATE[
        "running"
    ]:
        STATE[
            "stop_requested"
        ] = True

        STATE[
            "mode"
        ] = "STOPPING"

        STATE[
            "message"
        ] = (
            "Stopping safely after current operation"
        )

        return True

    return False

# ============================================================
# LIVE STATUS
# ============================================================

async def live_snapshot():
    databases = await database_snapshot()

    total_source = sum(
        item[
            "total"
        ]
        for item in databases.values()
    )

    uploaded = sum(
        item[
            "uploaded"
        ]
        for item in databases.values()
    )

    pending = sum(
        item[
            "pending"
        ]
        for item in databases.values()
    )

    failed = sum(
        item[
            "failed"
        ]
        for item in databases.values()
    )

    uploading = sum(
        item[
            "uploading"
        ]
        for item in databases.values()
    )

    return {
        "databases": databases,
        "total_source": total_source,
        "uploaded": uploaded,
        "pending": pending,
        "failed": failed,
        "uploading": uploading,
        "state": dict(STATE),
    }

# ============================================================
# STATUS PAGE (with colorful progress bar)
# ============================================================

async def build_status_page():
    snapshot = await live_snapshot()

    state = snapshot[
        "state"
    ]

    total = snapshot[
        "total_source"
    ]

    uploaded = snapshot[
        "uploaded"
    ]

    pending = snapshot[
        "pending"
    ]

    failed = snapshot[
        "failed"
    ]

    percent = (
        uploaded
        / total
        * 100
        if total
        else 100
    )

    runtime = 0

    if state.get(
        "started_at"
    ):
        runtime = (
            now()
            - state[
                "started_at"
            ]
        ).total_seconds()

    text = (
        "╔══════════════════════════════════════╗\n"
        "║ 🗄️ <b>DOWNTOWN VILLA BACKUP CORE</b> ║\n"
        "╚══════════════════════════════════════╝\n\n"

        f"{status_icon(state.get('mode'))} "
        f"<b>{html_escape(state.get('mode'))}</b>\n"

        f"📡 Channel: "
        f"<code>{get_backup_channel_id() or 'NOT SET'}</code>\n"

        f"🕒 {now_text()}\n"

        f"⏱️ Runtime: "
        f"<b>{fmt_duration(runtime)}</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>GLOBAL BACKUP</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📚 Source files: "
        f"<b>{fmt_int(total)}</b>\n"

        f"✅ Confirmed: "
        f"<b>{fmt_int(uploaded)}</b>\n"

        f"⏳ Pending: "
        f"<b>{fmt_int(pending)}</b>\n"

        f"❌ Failed: "
        f"<b>{fmt_int(failed)}</b>\n"

        f"📈 Progress: "
        f"<b>{percent:.2f}%</b>\n"

        f"<code>{progress_bar(uploaded, total, 28)}</code>\n"

        f"⚡ Speed: "
        f"<b>{fmt_float(state.get('speed'), 2)}/sec</b>\n"

        f"🎯 ETA: "
        f"<b>{fmt_duration(state.get('eta')) if state.get('eta') else '—'}</b>\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🗃️ <b>DATABASE STATUS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    for name, item in snapshot["databases"].items():
        # Only show databases with source files or non-zero counts
        if item["total"] <= 0 and item["uploaded"] <= 0 and item["failed"] <= 0:
            continue

        db_percent = (
            item["uploaded"] / item["total"] * 100
            if item["total"] else 100
        )

        text += (
            f"📦 <b>{html_escape(name)}</b>\n"
            f"   Source    : <b>{fmt_int(item['total'])}</b>\n"
            f"   Uploaded  : <b>{fmt_int(item['uploaded'])}</b>\n"
            f"   Pending   : <b>{fmt_int(item['pending'])}</b>\n"
            f"   Uploading : <b>{fmt_int(item['uploading'])}</b>\n"
            f"   Failed    : <b>{fmt_int(item['failed'])}</b>\n"
            f"   {progress_bar(item['uploaded'], item['total'], 18)}\n\n"
        )

    text += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎬 <b>CURRENT OPERATION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        f"🗃️ DB: "
        f"<b>{html_escape(state.get('current_db'))}</b>\n"

        f"🎬 File: "
        f"<code>{short(state.get('current_file'), 100)}</code>\n"

        f"🆔 File ID: "
        f"<code>{short(state.get('current_file_id'), 100)}</code>\n"

        f"💾 Size: "
        f"<b>{fmt_bytes(state.get('current_file_size'))}</b>\n"

        f"📨 Telegram ID: "
        f"<code>{state.get('last_message_id') or '-'}</code>\n"

        f"💬 {short(state.get('message'), 180)}\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛰️ <b>WATCHER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        f"🔄 Mode: "
        f"<b>{html_escape(state.get('mode'))}</b>\n"

        f"🕒 Last scan: "
        f"<code>{html_escape(state.get('last_scan'))}</code>\n"

        f"🧩 Worker PID: "
        f"<code>{os.getpid()}</code>\n"
    )

    if state.get(
        "last_error"
    ):
        text += (
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>LAST ERROR</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{short(state.get('last_error'), 700)}</code>\n"
        )

    return text[:4000]

# ============================================================
# FAILURE PAGE
# ============================================================

async def build_failure_page():
    collection = state_collection()

    if collection is None:
        return (
            "❌ Backup state collection unavailable."
        )

    cursor = collection.find(
        {
            "status": "FAILED",
        }
    ).sort(
        "updated_at",
        -1,
    ).limit(
        25
    )

    records = await cursor.to_list(
        length=25
    )

    text = (
        "❌ <b>BACKUP FAILURES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not records:
        return (
            text
            + "🟢 No failed files."
        )

    for item in records:
        text += (
            f"🔴 <b>{html_escape(item.get('source_db'))}</b>\n"
            f"🎬 {short(item.get('file_name'), 90)}\n"
            f"🆔 <code>{short(item.get('file_id'), 90)}</code>\n"
            f"🔁 Attempts: <b>{fmt_int(item.get('attempts', 0))}</b>\n"
            f"⚠️ {short(item.get('last_error'), 180)}\n\n"
        )

    return text[:4000]

# ============================================================
# HISTORY PAGE
# ============================================================

async def build_history_page():
    records = await get_history(
        12
    )

    text = (
        "🧾 <b>BACKUP HISTORY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not records:
        return (
            text
            + "💤 No runs recorded."
        )

    for item in records:
        started = item.get(
            "started_at"
        )

        finished = item.get(
            "finished_at"
        )

        if started:
            started_text = started.strftime(
                "%d %b %Y %H:%M:%S"
            )
        else:
            started_text = "-"

        duration = "running"

        if started and finished:
            duration = fmt_duration(
                (
                    finished
                    - started
                ).total_seconds()
            )

        status = str(
            item.get(
                "status",
                "UNKNOWN",
            )
        )

        text += (
            f"{status_icon(status)} "
            f"<b>{html_escape(status)}</b>\n"
            f"🕒 {started_text} UTC\n"
            f"⏱️ {duration}\n"
            f"✅ {fmt_int(item.get('uploaded', 0))}  "
            f"❌ {fmt_int(item.get('failed', 0))}  "
            f"⏭️ {fmt_int(item.get('skipped', 0))}\n\n"
        )

    return text[:4000]

# ============================================================
# BUTTONS
# ============================================================

def backup_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 LIVE",
                callback_data="dtv_backup_live",
            ),
            InlineKeyboardButton(
                "▶️ START",
                callback_data="dtv_backup_start",
            ),
        ],
        [
            InlineKeyboardButton(
                "⏸️ PAUSE",
                callback_data="dtv_backup_pause",
            ),
            InlineKeyboardButton(
                "▶️ RESUME",
                callback_data="dtv_backup_resume",
            ),
        ],
        [
            InlineKeyboardButton(
                "⏹️ STOP",
                callback_data="dtv_backup_stop",
            ),
            InlineKeyboardButton(
                "🔁 RETRY FAILED",
                callback_data="dtv_backup_retry",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 RESET STATE",
                callback_data="dtv_backup_reset_state",
            ),
            InlineKeyboardButton(
                "❌ CLEAR FAILURES",
                callback_data="dtv_backup_clear_failures",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ FAILURES",
                callback_data="dtv_backup_failures",
            ),
            InlineKeyboardButton(
                "🧾 HISTORY",
                callback_data="dtv_backup_history",
            ),
        ],
        [
            InlineKeyboardButton(
                "♻️ RECONCILE",
                callback_data="dtv_backup_reconcile",
            ),
            InlineKeyboardButton(
                "❌ CLOSE",
                callback_data="dtv_backup_close",
            ),
        ],
    ])

# ============================================================
# SAFE EDIT
# ============================================================

async def safe_edit(
    message,
    text,
    keyboard=None,
):
    try:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

        return True

    except RPCError as exc:
        if "MESSAGE_NOT_MODIFIED" in str(
            exc
        ).upper():
            return True

        logger.warning(
            "Backup panel edit failed: %s",
            exc,
        )

    except Exception as exc:
        logger.warning(
            "Backup panel edit error: %s",
            exc,
        )

    return False

# ============================================================
# LIVE PANEL UPDATER
# ============================================================

async def live_panel_loop(
    client,
    message,
    page="live",
):
    last_text = None

    while True:
        try:
            if page == "live":
                text = await build_status_page()
            elif page == "history":
                text = await build_history_page()
            elif page == "failures":
                text = await build_failure_page()
            else:
                text = await build_status_page()

            if text != last_text:
                await safe_edit(
                    message,
                    text,
                    backup_keyboard(),
                )

                last_text = text

            await asyncio.sleep(
                2
            )

            record = ACTIVE_PANELS.get(
                message.id
            )

            if not record:
                break

            if record.get(
                "closed"
            ):
                break

            if record.get(
                "page"
            ) != page:
                break

        except asyncio.CancelledError:
            break

        except Exception:
            logger.exception(
                "Backup live panel error"
            )
            await asyncio.sleep(
                3
            )

def stop_panel(
    message_id,
):
    record = ACTIVE_PANELS.get(
        message_id
    )

    if record:
        record[
            "closed"
        ] = True

        task = record.get(
            "task"
        )

        if task:
            try:
                task.cancel()
            except Exception:
                pass

def open_panel(
    message,
    page="live",
):
    stop_panel(
        message.id
    )

    task = asyncio.create_task(
        live_panel_loop(
            STATE.get(
                "_client"
            ),
            message,
            page,
        )
    )

    ACTIVE_PANELS[
        message.id
    ] = {
        "page": page,
        "task": task,
        "closed": False,
        "created": time.time(),
    }

    return task

# ============================================================
# /backup — THE ONLY COMMAND
# ============================================================

@Client.on_message(
    filters.command(
        "backup"
    )
)
async def backup_command(
    client,
    message,
):
    user = message.from_user

    if user is None or not is_admin(
        user.id
    ):
        return

    STATE[
        "_client"
    ] = client

    await ensure_indexes()

    ensure_watcher(
        client
    )

    text = await build_status_page()

    sent = await message.reply_text(
        text,
        reply_markup=backup_keyboard(),
        disable_web_page_preview=True,
    )

    open_panel(
        sent,
        "live",
    )

# ============================================================
# CALLBACKS
# ============================================================

@Client.on_callback_query(
    filters.regex(
        r"^dtv_backup_"
    )
)
async def backup_callback(
    client,
    query,
):
    user = query.from_user

    if user is None or not is_admin(
        user.id
    ):
        await query.answer(
            "❌ Access denied",
            show_alert=True,
        )
        return

    STATE[
        "_client"
    ] = client

    data = str(
        query.data
    )

    try:
        if data == "dtv_backup_live":
            await query.answer(
                "🔄 Live monitoring",
            )

            text = await build_status_page()

            await safe_edit(
                query.message,
                text,
                backup_keyboard(),
            )

            open_panel(
                query.message,
                "live",
            )

            return

        if data == "dtv_backup_start":
            started = await start_backup(
                client
            )

            ensure_watcher(
                client
            )

            await query.answer(
                "▶️ Backup started"
                if started
                else "🟡 Backup already running",
            )

            return

        if data == "dtv_backup_pause":
            changed = pause_backup()

            await query.answer(
                "⏸️ Backup paused"
                if changed
                else "🟡 Nothing is running",
            )

            return

        if data == "dtv_backup_resume":
            changed = resume_backup()

            await query.answer(
                "▶️ Backup resumed"
                if changed
                else "🟡 Backup is not paused",
            )

            return

        if data == "dtv_backup_stop":
            changed = stop_backup()

            await query.answer(
                "⏹️ Stop requested"
                if changed
                else "🟡 Nothing is running",
            )

            return

        if data == "dtv_backup_retry":
            started = await retry_failed_files(
                client
            )

            await query.answer(
                "🔁 Failed files retry started"
                if started
                else "🟡 Backup already running",
            )

            return

        # NEW: Reset all backup state (force re-upload everything)
        if data == "dtv_backup_reset_state":
            if STATE["running"]:
                await query.answer(
                    "⏸️ Stop the backup first before resetting state.",
                    show_alert=True,
                )
                return

            count = await reset_all_state()
            await query.answer(
                f"🔄 Reset {count} state records. All files will be re-uploaded on next start.",
                show_alert=True,
            )
            return

        # NEW: Clear only failed records (retry them)
        if data == "dtv_backup_clear_failures":
            count = await reset_failed()
            await query.answer(
                f"✅ Cleared {count} failed records. They will be retried on next start.",
                show_alert=True,
            )
            return


        if data == "dtv_backup_reconcile":
            await query.answer(
                "♻️ Reconciliation started",
            )

            asyncio.create_task(
                reconcile_interrupted()
            )

            return

        if data == "dtv_backup_history":
            text = await build_history_page()

            await safe_edit(
                query.message,
                text,
                backup_keyboard(),
            )

            open_panel(
                query.message,
                "history",
            )

            await query.answer(
                "🧾 History",
            )

            return

        if data == "dtv_backup_failures":
            text = await build_failure_page()

            await safe_edit(
                query.message,
                text,
                backup_keyboard(),
            )

            open_panel(
                query.message,
                "failures",
            )

            await query.answer(
                "❌ Failed files",
            )

            return

        if data == "dtv_backup_close":
            stop_panel(
                query.message.id
            )

            ACTIVE_PANELS.pop(
                query.message.id,
                None,
            )

            await query.message.delete()

            return

    except Exception as exc:
        logger.exception(
            "Backup callback error"
        )

        try:
            await query.answer(
                f"❌ {short(exc, 150)}",
                show_alert=True,
            )
        except Exception:
            pass

# ============================================================
# AUTO START
# ============================================================

async def initialize_backup(
    client,
):
    """
    Optional integration hook.
    The watcher starts even if BACKUP_AUTO_START is false.
    If BACKUP_AUTO_START=true, an initial resumable pass starts.
    """

    STATE[
        "_client"
    ] = client

    await ensure_indexes()

    ensure_watcher(
        client
    )

    if not BACKUP_AUTO_START:
        return

    if not STATE[
        "running"
    ]:
        await start_backup(
            client
        )
