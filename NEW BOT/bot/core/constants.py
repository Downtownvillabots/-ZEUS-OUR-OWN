"""
bot.core.constants

Centralized constants for the application.

Keep values that are shared across multiple modules here instead
of scattering magic strings and numbers throughout the project.

IMPORTANT:
    Environment-specific secrets, tokens, passwords, API keys,
    database credentials, and other deployment configuration do
    NOT belong in this file. Those belong in config.py/environment
    variables.

This module contains application-level constants only.
"""

from __future__ import annotations


# ============================================================================
# Application identity
# ============================================================================

APP_NAME = "Telegram File Bot"

APP_VERSION = "1.0.0"

APP_DESCRIPTION = (
    "Telegram bot for file discovery, search, delivery, "
    "movie discovery, verification, premium access, "
    "broadcasting, and moderation."
)

APP_AUTHOR = "Software Architecture Team"

APP_ENVIRONMENT_VARIABLE = "BOT_ENV"


# ============================================================================
# Environments
# ============================================================================

ENV_DEVELOPMENT = "development"

ENV_TESTING = "testing"

ENV_STAGING = "staging"

ENV_PRODUCTION = "production"

VALID_ENVIRONMENTS = frozenset(
    {
        ENV_DEVELOPMENT,
        ENV_TESTING,
        ENV_STAGING,
        ENV_PRODUCTION,
    }
)


# ============================================================================
# Default runtime values
# ============================================================================

DEFAULT_TIMEZONE = "UTC"

DEFAULT_LANGUAGE = "en"

DEFAULT_PAGE_SIZE = 10

MAX_PAGE_SIZE = 100

MIN_PAGE_SIZE = 1

DEFAULT_SEARCH_LIMIT = 20

MAX_SEARCH_LIMIT = 100

DEFAULT_CACHE_TTL_SECONDS = 300

DEFAULT_SESSION_TTL_SECONDS = 3600

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10

DEFAULT_READ_TIMEOUT_SECONDS = 30

DEFAULT_WRITE_TIMEOUT_SECONDS = 30

DEFAULT_POOL_TIMEOUT_SECONDS = 10


# ============================================================================
# Telegram limits
# ============================================================================

TELEGRAM_CALLBACK_DATA_MAX_BYTES = 64

TELEGRAM_MESSAGE_MAX_LENGTH = 4096

TELEGRAM_CAPTION_MAX_LENGTH = 1024

TELEGRAM_USERNAME_MAX_LENGTH = 32

TELEGRAM_USERNAME_MIN_LENGTH = 5

TELEGRAM_COMMAND_MAX_LENGTH = 32

TELEGRAM_MAX_INLINE_RESULTS = 50

TELEGRAM_MAX_MEDIA_GROUP_SIZE = 10

TELEGRAM_MAX_BUTTONS_PER_ROW = 8

TELEGRAM_MAX_KEYBOARD_ROWS = 100


# ============================================================================
# Search
# ============================================================================

SEARCH_MIN_QUERY_LENGTH = 2

SEARCH_MAX_QUERY_LENGTH = 200

SEARCH_DEFAULT_PAGE = 1

SEARCH_DEFAULT_SORT = "relevance"

SEARCH_DEFAULT_LANGUAGE = "any"

SEARCH_DEFAULT_QUALITY = "any"

SEARCH_DEFAULT_YEAR = "any"

SEARCH_DEFAULT_FILE_TYPE = "any"

SEARCH_DEFAULT_SIZE_FILTER = "any"

SEARCH_MAX_RESULTS = 100

SEARCH_MAX_HISTORY_ITEMS = 50

SEARCH_DEBOUNCE_SECONDS = 0.5

SEARCH_RATE_LIMIT_REQUESTS = 5

SEARCH_RATE_LIMIT_WINDOW_SECONDS = 10


# ============================================================================
# Search sort modes
# ============================================================================

SORT_RELEVANCE = "relevance"

SORT_NEWEST = "newest"

SORT_OLDEST = "oldest"

SORT_NAME_ASC = "name_asc"

SORT_NAME_DESC = "name_desc"

SORT_SIZE_ASC = "size_asc"

SORT_SIZE_DESC = "size_desc"

VALID_SORT_MODES = frozenset(
    {
        SORT_RELEVANCE,
        SORT_NEWEST,
        SORT_OLDEST,
        SORT_NAME_ASC,
        SORT_NAME_DESC,
        SORT_SIZE_ASC,
        SORT_SIZE_DESC,
    }
)


# ============================================================================
# File types
# ============================================================================

FILE_TYPE_ANY = "any"

FILE_TYPE_VIDEO = "video"

FILE_TYPE_AUDIO = "audio"

FILE_TYPE_DOCUMENT = "document"

FILE_TYPE_IMAGE = "image"

FILE_TYPE_ARCHIVE = "archive"

FILE_TYPE_OTHER = "other"

VALID_FILE_TYPES = frozenset(
    {
        FILE_TYPE_ANY,
        FILE_TYPE_VIDEO,
        FILE_TYPE_AUDIO,
        FILE_TYPE_DOCUMENT,
        FILE_TYPE_IMAGE,
        FILE_TYPE_ARCHIVE,
        FILE_TYPE_OTHER,
    }
)


# ============================================================================
# File extensions
# ============================================================================

VIDEO_EXTENSIONS = frozenset(
    {
        "mp4",
        "mkv",
        "avi",
        "mov",
        "wmv",
        "flv",
        "webm",
        "m4v",
        "3gp",
        "mpeg",
        "mpg",
        "ts",
        "m2ts",
    }
)

AUDIO_EXTENSIONS = frozenset(
    {
        "mp3",
        "m4a",
        "aac",
        "flac",
        "wav",
        "ogg",
        "oga",
        "opus",
        "wma",
        "alac",
        "aiff",
    }
)

IMAGE_EXTENSIONS = frozenset(
    {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "bmp",
        "tiff",
        "tif",
        "svg",
        "ico",
        "heic",
        "heif",
    }
)

DOCUMENT_EXTENSIONS = frozenset(
    {
        "pdf",
        "txt",
        "md",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "csv",
        "ppt",
        "pptx",
        "odt",
        "ods",
        "odp",
        "rtf",
    }
)

ARCHIVE_EXTENSIONS = frozenset(
    {
        "zip",
        "rar",
        "7z",
        "tar",
        "gz",
        "bz2",
        "xz",
        "tgz",
        "tbz",
    }
)


# ============================================================================
# Movie
# ============================================================================

MOVIE_DEFAULT_PAGE_SIZE = 10

MOVIE_MAX_PAGE_SIZE = 50

MOVIE_MIN_YEAR = 1888

MOVIE_MAX_YEAR = 2100

MOVIE_DEFAULT_LANGUAGE = "any"

MOVIE_DEFAULT_REGION = "any"

MOVIE_DEFAULT_SORT = SORT_RELEVANCE


# ============================================================================
# Movie genres
# ============================================================================

GENRE_ACTION = "action"

GENRE_ADVENTURE = "adventure"

GENRE_ANIMATION = "animation"

GENRE_COMEDY = "comedy"

GENRE_CRIME = "crime"

GENRE_DOCUMENTARY = "documentary"

GENRE_DRAMA = "drama"

GENRE_FAMILY = "family"

GENRE_FANTASY = "fantasy"

GENRE_HISTORY = "history"

GENRE_HORROR = "horror"

GENRE_MUSIC = "music"

GENRE_MYSTERY = "mystery"

GENRE_ROMANCE = "romance"

GENRE_SCIENCE_FICTION = "science_fiction"

GENRE_THRILLER = "thriller"

GENRE_WAR = "war"

GENRE_WESTERN = "western"

VALID_MOVIE_GENRES = frozenset(
    {
        GENRE_ACTION,
        GENRE_ADVENTURE,
        GENRE_ANIMATION,
        GENRE_COMEDY,
        GENRE_CRIME,
        GENRE_DOCUMENTARY,
        GENRE_DRAMA,
        GENRE_FAMILY,
        GENRE_FANTASY,
        GENRE_HISTORY,
        GENRE_HORROR,
        GENRE_MUSIC,
        GENRE_MYSTERY,
        GENRE_ROMANCE,
        GENRE_SCIENCE_FICTION,
        GENRE_THRILLER,
        GENRE_WAR,
        GENRE_WESTERN,
    }
)


# ============================================================================
# Quality
# ============================================================================

QUALITY_ANY = "any"

QUALITY_CAM = "cam"

QUALITY_HDCAM = "hdcam"

QUALITY_TS = "ts"

QUALITY_TC = "tc"

QUALITY_DVDSCR = "dvdscr"

QUALITY_WEBRIP = "webrip"

QUALITY_WEB_DL = "web-dl"

QUALITY_HDRIP = "hdrip"

QUALITY_BRRIP = "brrip"

QUALITY_BLURAY = "bluray"

QUALITY_480P = "480p"

QUALITY_720P = "720p"

QUALITY_1080P = "1080p"

QUALITY_2160P = "2160p"

QUALITY_4K = "4k"

VALID_QUALITIES = frozenset(
    {
        QUALITY_ANY,
        QUALITY_CAM,
        QUALITY_HDCAM,
        QUALITY_TS,
        QUALITY_TC,
        QUALITY_DVDSCR,
        QUALITY_WEBRIP,
        QUALITY_WEB_DL,
        QUALITY_HDRIP,
        QUALITY_BRRIP,
        QUALITY_BLURAY,
        QUALITY_480P,
        QUALITY_720P,
        QUALITY_1080P,
        QUALITY_2160P,
        QUALITY_4K,
    }
)


# ============================================================================
# Languages
# ============================================================================

LANGUAGE_ANY = "any"

LANGUAGE_ENGLISH = "english"

LANGUAGE_HINDI = "hindi"

LANGUAGE_TELUGU = "telugu"

LANGUAGE_TAMIL = "tamil"

LANGUAGE_KANNADA = "kannada"

LANGUAGE_MALAYALAM = "malayalam"

LANGUAGE_BENGALI = "bengali"

LANGUAGE_MARATHI = "marathi"

LANGUAGE_PUNJABI = "punjabi"

LANGUAGE_GUJARATI = "gujarati"

LANGUAGE_URDU = "urdu"

VALID_LANGUAGES = frozenset(
    {
        LANGUAGE_ANY,
        LANGUAGE_ENGLISH,
        LANGUAGE_HINDI,
        LANGUAGE_TELUGU,
        LANGUAGE_TAMIL,
        LANGUAGE_KANNADA,
        LANGUAGE_MALAYALAM,
        LANGUAGE_BENGALI,
        LANGUAGE_MARATHI,
        LANGUAGE_PUNJABI,
        LANGUAGE_GUJARATI,
        LANGUAGE_URDU,
    }
)


# ============================================================================
# User roles
# ============================================================================

ROLE_USER = "user"

ROLE_MODERATOR = "moderator"

ROLE_ADMIN = "admin"

ROLE_OWNER = "owner"

VALID_ROLES = frozenset(
    {
        ROLE_USER,
        ROLE_MODERATOR,
        ROLE_ADMIN,
        ROLE_OWNER,
    }
)


# ============================================================================
# User status
# ============================================================================

USER_STATUS_ACTIVE = "active"

USER_STATUS_INACTIVE = "inactive"

USER_STATUS_BANNED = "banned"

USER_STATUS_BLOCKED = "blocked"

USER_STATUS_DELETED = "deleted"

USER_STATUS_PENDING = "pending"

VALID_USER_STATUSES = frozenset(
    {
        USER_STATUS_ACTIVE,
        USER_STATUS_INACTIVE,
        USER_STATUS_BANNED,
        USER_STATUS_BLOCKED,
        USER_STATUS_DELETED,
        USER_STATUS_PENDING,
    }
)


# ============================================================================
# Subscription
# ============================================================================

SUBSCRIPTION_FREE = "free"

SUBSCRIPTION_PREMIUM = "premium"

SUBSCRIPTION_ADMIN = "admin"

SUBSCRIPTION_EXPIRED = "expired"

SUBSCRIPTION_CANCELLED = "cancelled"

VALID_SUBSCRIPTION_STATUSES = frozenset(
    {
        SUBSCRIPTION_FREE,
        SUBSCRIPTION_PREMIUM,
        SUBSCRIPTION_ADMIN,
        SUBSCRIPTION_EXPIRED,
        SUBSCRIPTION_CANCELLED,
    }
)


# ============================================================================
# Payment
# ============================================================================

PAYMENT_PENDING = "pending"

PAYMENT_PROCESSING = "processing"

PAYMENT_COMPLETED = "completed"

PAYMENT_FAILED = "failed"

PAYMENT_CANCELLED = "cancelled"

PAYMENT_REFUNDED = "refunded"

VALID_PAYMENT_STATUSES = frozenset(
    {
        PAYMENT_PENDING,
        PAYMENT_PROCESSING,
        PAYMENT_COMPLETED,
        PAYMENT_FAILED,
        PAYMENT_CANCELLED,
        PAYMENT_REFUNDED,
    }
)


# ============================================================================
# Verification
# ============================================================================

VERIFICATION_PENDING = "pending"

VERIFICATION_VERIFIED = "verified"

VERIFICATION_EXPIRED = "expired"

VERIFICATION_FAILED = "failed"

VERIFICATION_BLOCKED = "blocked"

VALID_VERIFICATION_STATUSES = frozenset(
    {
        VERIFICATION_PENDING,
        VERIFICATION_VERIFIED,
        VERIFICATION_EXPIRED,
        VERIFICATION_FAILED,
        VERIFICATION_BLOCKED,
    }
)

VERIFICATION_TOKEN_LENGTH = 32

VERIFICATION_CODE_LENGTH = 6

VERIFICATION_TTL_SECONDS = 900

VERIFICATION_MAX_ATTEMPTS = 5

VERIFICATION_COOLDOWN_SECONDS = 60


# ============================================================================
# Delivery
# ============================================================================

DELIVERY_PENDING = "pending"

DELIVERY_PROCESSING = "processing"

DELIVERY_COMPLETED = "completed"

DELIVERY_FAILED = "failed"

DELIVERY_EXPIRED = "expired"

DELIVERY_CANCELLED = "cancelled"

VALID_DELIVERY_STATUSES = frozenset(
    {
        DELIVERY_PENDING,
        DELIVERY_PROCESSING,
        DELIVERY_COMPLETED,
        DELIVERY_FAILED,
        DELIVERY_EXPIRED,
        DELIVERY_CANCELLED,
    }
)

DELIVERY_DEFAULT_TTL_SECONDS = 3600

DELIVERY_MAX_RETRIES = 3

DELIVERY_RETRY_DELAY_SECONDS = 5

DELIVERY_RATE_LIMIT_REQUESTS = 3

DELIVERY_RATE_LIMIT_WINDOW_SECONDS = 30


# ============================================================================
# Shortener
# ============================================================================

SHORTENER_PROVIDER_DEFAULT = "default"

SHORTENER_TIMEOUT_SECONDS = 15

SHORTENER_MAX_RETRIES = 3

SHORTENER_CACHE_TTL_SECONDS = 3600

SHORTENER_URL_MAX_LENGTH = 4096


# ============================================================================
# Broadcast
# ============================================================================

BROADCAST_PENDING = "pending"

BROADCAST_SCHEDULED = "scheduled"

BROADCAST_PROCESSING = "processing"

BROADCAST_PAUSED = "paused"

BROADCAST_COMPLETED = "completed"

BROADCAST_FAILED = "failed"

BROADCAST_CANCELLED = "cancelled"

VALID_BROADCAST_STATUSES = frozenset(
    {
        BROADCAST_PENDING,
        BROADCAST_SCHEDULED,
        BROADCAST_PROCESSING,
        BROADCAST_PAUSED,
        BROADCAST_COMPLETED,
        BROADCAST_FAILED,
        BROADCAST_CANCELLED,
    }
)

BROADCAST_BATCH_SIZE = 25

BROADCAST_MAX_RETRIES = 3

BROADCAST_RETRY_DELAY_SECONDS = 2

BROADCAST_DEFAULT_RATE_LIMIT_PER_SECOND = 20


# ============================================================================
# Moderation
# ============================================================================

MODERATION_WARN = "warn"

MODERATION_MUTE = "mute"

MODERATION_BAN = "ban"

MODERATION_UNBAN = "unban"

MODERATION_BLOCK = "block"

MODERATION_UNBLOCK = "unblock"

MODERATION_REPORT = "report"

MODERATION_RESOLVE = "resolve"

MODERATION_REJECT = "reject"

VALID_MODERATION_ACTIONS = frozenset(
    {
        MODERATION_WARN,
        MODERATION_MUTE,
        MODERATION_BAN,
        MODERATION_UNBAN,
        MODERATION_BLOCK,
        MODERATION_UNBLOCK,
        MODERATION_REPORT,
        MODERATION_RESOLVE,
        MODERATION_REJECT,
    }
)

MODERATION_MAX_WARNINGS = 3

MODERATION_DEFAULT_MUTE_SECONDS = 3600


# ============================================================================
# Database
# ============================================================================

DB_POOL_MIN_SIZE = 1

DB_POOL_MAX_SIZE = 10

DB_CONNECTION_TIMEOUT_SECONDS = 10

DB_COMMAND_TIMEOUT_SECONDS = 30

DB_TRANSACTION_TIMEOUT_SECONDS = 60

DB_MAX_RETRIES = 3

DB_RETRY_DELAY_SECONDS = 1


# ============================================================================
# Cache
# ============================================================================

CACHE_KEY_PREFIX = "bot"

CACHE_DEFAULT_TTL_SECONDS = 300

CACHE_SEARCH_TTL_SECONDS = 120

CACHE_MOVIE_TTL_SECONDS = 600

CACHE_USER_TTL_SECONDS = 300

CACHE_FILE_TTL_SECONDS = 300

CACHE_VERIFICATION_TTL_SECONDS = 900


# ============================================================================
# Redis
# ============================================================================

REDIS_DEFAULT_PORT = 6379

REDIS_DEFAULT_DB = 0

REDIS_CONNECT_TIMEOUT_SECONDS = 5

REDIS_SOCKET_TIMEOUT_SECONDS = 5

REDIS_MAX_CONNECTIONS = 50


# ============================================================================
# Logging
# ============================================================================

LOG_LEVEL_DEBUG = "DEBUG"

LOG_LEVEL_INFO = "INFO"

LOG_LEVEL_WARNING = "WARNING"

LOG_LEVEL_ERROR = "ERROR"

LOG_LEVEL_CRITICAL = "CRITICAL"

DEFAULT_LOG_LEVEL = LOG_LEVEL_INFO

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)s | "
    "%(name)s | "
    "%(message)s"
)

DEFAULT_LOG_DATE_FORMAT = (
    "%Y-%m-%d %H:%M:%S"
)


# ============================================================================
# Middleware
# ============================================================================

MIDDLEWARE_AUTH = "auth"

MIDDLEWARE_ADMIN = "admin"

MIDDLEWARE_THROTTLING = "throttling"

MIDDLEWARE_LOGGING = "logging"

MIDDLEWARE_ERRORS = "errors"


# ============================================================================
# Rate limiting
# ============================================================================

DEFAULT_RATE_LIMIT_REQUESTS = 10

DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 5

DEFAULT_RATE_LIMIT_BURST = 3

DEFAULT_RATE_LIMIT_BLOCK_SECONDS = 2


# ============================================================================
# Pagination
# ============================================================================

PAGINATION_FIRST_PAGE = 1

PAGINATION_DEFAULT_SIZE = 10

PAGINATION_MAX_SIZE = 100

PAGINATION_WINDOW = 2


# ============================================================================
# Callback namespaces
# ============================================================================

CALLBACK_NAV = "nav"

CALLBACK_SEARCH = "search"

CALLBACK_MOVIE = "movie"

CALLBACK_FILE = "file"

CALLBACK_FILTER = "filter"

CALLBACK_PREMIUM = "premium"

CALLBACK_SETTINGS = "settings"

CALLBACK_VERIFICATION = "verification"

CALLBACK_ADMIN = "admin"

CALLBACK_MODERATION = "moderation"

CALLBACK_BROADCAST = "broadcast"

CALLBACK_SYSTEM = "system"

CALLBACK_NOOP = "noop"


# ============================================================================
# Navigation callbacks
# ============================================================================

CB_HOME = "nav:home"

CB_BACK = "nav:back"

CB_SEARCH = "nav:search"

CB_MOVIES = "nav:movies"

CB_FILES = "nav:files"

CB_PREMIUM = "nav:premium"

CB_SETTINGS = "nav:settings"

CB_HELP = "nav:help"


# ============================================================================
# Common text
# ============================================================================

TEXT_HOME = "🏠 Home"

TEXT_BACK = "⬅️ Back"

TEXT_CANCEL = "❌ Cancel"

TEXT_CONFIRM = "✅ Confirm"

TEXT_SEARCH = "🔎 Search"

TEXT_FILTERS = "🎛 Filters"

TEXT_SETTINGS = "⚙️ Settings"

TEXT_HELP = "❓ Help"

TEXT_PREMIUM = "💎 Premium"

TEXT_FILES = "📁 Files"

TEXT_MOVIES = "🎬 Movies"

TEXT_ADMIN = "🛠 Admin Panel"

TEXT_LOADING = "⏳ Loading..."

TEXT_PROCESSING = "⚙️ Processing..."

TEXT_SUCCESS = "✅ Done"

TEXT_ERROR = "⚠️ Something went wrong."

TEXT_NOT_FOUND = "❌ Nothing found."

TEXT_UNAUTHORIZED = "⛔ You are not authorized."

TEXT_BANNED = "🚫 You are not allowed to use this bot."

TEXT_RETRY = "🔄 Try Again"


# ============================================================================
# Callback validation
# ============================================================================

CALLBACK_SEPARATOR = ":"

CALLBACK_MAX_PARTS = 10


# ============================================================================
# File size constants
# ============================================================================

BYTES_PER_KB = 1024

BYTES_PER_MB = (
    BYTES_PER_KB
    * 1024
)

BYTES_PER_GB = (
    BYTES_PER_MB
    * 1024
)

BYTES_PER_TB = (
    BYTES_PER_GB
    * 1024
)

MAX_FILE_SIZE_BYTES = (
    2 * BYTES_PER_GB
)


# ============================================================================
# Time constants
# ============================================================================

SECONDS_PER_MINUTE = 60

SECONDS_PER_HOUR = (
    60
    * SECONDS_PER_MINUTE
)

SECONDS_PER_DAY = (
    24
    * SECONDS_PER_HOUR
)

SECONDS_PER_WEEK = (
    7
    * SECONDS_PER_DAY
)


# ============================================================================
# HTTP status constants
# ============================================================================

HTTP_OK = 200

HTTP_CREATED = 201

HTTP_ACCEPTED = 202

HTTP_NO_CONTENT = 204

HTTP_BAD_REQUEST = 400

HTTP_UNAUTHORIZED = 401

HTTP_FORBIDDEN = 403

HTTP_NOT_FOUND = 404

HTTP_CONFLICT = 409

HTTP_TOO_MANY_REQUESTS = 429

HTTP_INTERNAL_SERVER_ERROR = 500

HTTP_BAD_GATEWAY = 502

HTTP_SERVICE_UNAVAILABLE = 503

HTTP_GATEWAY_TIMEOUT = 504


# ============================================================================
# MIME types
# ============================================================================

MIME_VIDEO = "video/*"

MIME_AUDIO = "audio/*"

MIME_IMAGE = "image/*"

MIME_APPLICATION_OCTET_STREAM = (
    "application/octet-stream"
)

MIME_APPLICATION_PDF = (
    "application/pdf"
)

MIME_APPLICATION_ZIP = (
    "application/zip"
)


# ============================================================================
# Feature flags
# ============================================================================

FEATURE_SEARCH = "search"

FEATURE_MOVIES = "movies"

FEATURE_FILE_DELIVERY = "file_delivery"

FEATURE_PREMIUM = "premium"

FEATURE_VERIFICATION = "verification"

FEATURE_BROADCAST = "broadcast"

FEATURE_MODERATION = "moderation"

FEATURE_SHORTENER = "shortener"

FEATURE_INDEXER = "indexer"


# ============================================================================
# Default feature state
# ============================================================================

DEFAULT_FEATURES = {
    FEATURE_SEARCH: True,
    FEATURE_MOVIES: True,
    FEATURE_FILE_DELIVERY: True,
    FEATURE_PREMIUM: True,
    FEATURE_VERIFICATION: True,
    FEATURE_BROADCAST: True,
    FEATURE_MODERATION: True,
    FEATURE_SHORTENER: True,
    FEATURE_INDEXER: True,
}


# ============================================================================
# Environment variable names
# ============================================================================

ENV_BOT_TOKEN = "BOT_TOKEN"

ENV_DATABASE_URL = "DATABASE_URL"

ENV_REDIS_URL = "REDIS_URL"

ENV_ADMIN_IDS = "ADMIN_IDS"

ENV_LOG_LEVEL = "LOG_LEVEL"

ENV_TIMEZONE = "TIMEZONE"

ENV_WEBHOOK_URL = "WEBHOOK_URL"

ENV_WEBHOOK_SECRET = "WEBHOOK_SECRET"

ENV_WEBHOOK_PORT = "WEBHOOK_PORT"

ENV_WEBHOOK_PATH = "WEBHOOK_PATH"

ENV_ENVIRONMENT = "BOT_ENV"

ENV_DEBUG = "DEBUG"

ENV_TESTING = "TESTING"

ENV_SECRET_KEY = "SECRET_KEY"

ENV_ENCRYPTION_KEY = "ENCRYPTION_KEY"

ENV_SHORTENER_API_KEY = "SHORTENER_API_KEY"

ENV_MOVIE_API_KEY = "MOVIE_API_KEY"

ENV_STORAGE_BUCKET = "STORAGE_BUCKET"

ENV_STORAGE_ENDPOINT = "STORAGE_ENDPOINT"

ENV_STORAGE_ACCESS_KEY = "STORAGE_ACCESS_KEY"

ENV_STORAGE_SECRET_KEY = "STORAGE_SECRET_KEY"


# ============================================================================
# Validation groups
# ============================================================================

REQUIRED_PRODUCTION_ENV_VARS = frozenset(
    {
        ENV_BOT_TOKEN,
        ENV_DATABASE_URL,
        ENV_SECRET_KEY,
    }
)


# ============================================================================
# API versions
# ============================================================================

INTERNAL_API_VERSION = "v1"

API_PREFIX = f"/api/{INTERNAL_API_VERSION}"


# ============================================================================
# Health endpoints
# ============================================================================

HEALTH_PATH = "/health"

READINESS_PATH = "/ready"

LIVENESS_PATH = "/live"

METRICS_PATH = "/metrics"


# ============================================================================
# Event names
# ============================================================================

EVENT_APP_STARTING = "app.starting"

EVENT_APP_STARTED = "app.started"

EVENT_APP_STOPPING = "app.stopping"

EVENT_APP_STOPPED = "app.stopped"

EVENT_USER_REGISTERED = "user.registered"

EVENT_USER_BANNED = "user.banned"

EVENT_USER_UNBANNED = "user.unbanned"

EVENT_SEARCH_STARTED = "search.started"

EVENT_SEARCH_COMPLETED = "search.completed"

EVENT_SEARCH_FAILED = "search.failed"

EVENT_FILE_REQUESTED = "file.requested"

EVENT_FILE_DELIVERED = "file.delivered"

EVENT_FILE_FAILED = "file.failed"

EVENT_PAYMENT_STARTED = "payment.started"

EVENT_PAYMENT_COMPLETED = "payment.completed"

EVENT_PAYMENT_FAILED = "payment.failed"

EVENT_VERIFICATION_STARTED = "verification.started"

EVENT_VERIFICATION_COMPLETED = "verification.completed"

EVENT_BROADCAST_STARTED = "broadcast.started"

EVENT_BROADCAST_COMPLETED = "broadcast.completed"

EVENT_BROADCAST_FAILED = "broadcast.failed"


# ============================================================================
# Queue names
# ============================================================================

QUEUE_DEFAULT = "default"

QUEUE_SEARCH = "search"

QUEUE_INDEXING = "indexing"

QUEUE_DELIVERY = "delivery"

QUEUE_BROADCAST = "broadcast"

QUEUE_NOTIFICATIONS = "notifications"

QUEUE_CLEANUP = "cleanup"


# ============================================================================
# Job statuses
# ============================================================================

JOB_PENDING = "pending"

JOB_RUNNING = "running"

JOB_COMPLETED = "completed"

JOB_FAILED = "failed"

JOB_CANCELLED = "cancelled"

JOB_RETRYING = "retrying"

VALID_JOB_STATUSES = frozenset(
    {
        JOB_PENDING,
        JOB_RUNNING,
        JOB_COMPLETED,
        JOB_FAILED,
        JOB_CANCELLED,
        JOB_RETRYING,
    }
)


# ============================================================================
# Generic limits
# ============================================================================

MAX_USERNAME_LENGTH = 32

MAX_DISPLAY_NAME_LENGTH = 128

MAX_SEARCH_HISTORY_QUERY_LENGTH = 200

MAX_CALLBACK_ID_LENGTH = 64

MAX_ERROR_MESSAGE_LENGTH = 1000

MAX_LOG_MESSAGE_LENGTH = 10000

MAX_BROADCAST_MESSAGE_LENGTH = 4096

MAX_MOVIE_TITLE_LENGTH = 500

MAX_FILE_NAME_LENGTH = 255

MAX_DESCRIPTION_LENGTH = 4096

MAX_URL_LENGTH = 4096


# ============================================================================
# Security
# ============================================================================

PASSWORD_MIN_LENGTH = 12

TOKEN_MIN_LENGTH = 16

TOKEN_MAX_LENGTH = 256

MAX_LOGIN_ATTEMPTS = 5

LOGIN_LOCKOUT_SECONDS = 900

SECURITY_TOKEN_TTL_SECONDS = 3600

SIGNED_URL_TTL_SECONDS = 900


# ============================================================================
# Cleanup
# ============================================================================

CLEANUP_INTERVAL_SECONDS = 300

EXPIRED_SESSION_CLEANUP_INTERVAL = 3600

EXPIRED_VERIFICATION_CLEANUP_INTERVAL = 900

EXPIRED_DELIVERY_CLEANUP_INTERVAL = 900

EXPIRED_CACHE_CLEANUP_INTERVAL = 600


# ============================================================================
# Development
# ============================================================================

DEVELOPMENT_RELOAD = True

DEVELOPMENT_DEBUG = True

TESTING_DEBUG = False

PRODUCTION_DEBUG = False


# ============================================================================
# Utility mappings
# ============================================================================

QUALITY_RANK = {
    QUALITY_ANY: 0,
    QUALITY_CAM: 1,
    QUALITY_HDCAM: 2,
    QUALITY_TS: 3,
    QUALITY_TC: 4,
    QUALITY_DVDSCR: 5,
    QUALITY_HDRIP: 6,
    QUALITY_WEBRIP: 7,
    QUALITY_WEB_DL: 8,
    QUALITY_BRRIP: 9,
    QUALITY_BLURAY: 10,
    QUALITY_480P: 11,
    QUALITY_720P: 12,
    QUALITY_1080P: 13,
    QUALITY_2160P: 14,
    QUALITY_4K: 15,
}


FILE_TYPE_LABELS = {
    FILE_TYPE_ANY: "Any",
    FILE_TYPE_VIDEO: "Video",
    FILE_TYPE_AUDIO: "Audio",
    FILE_TYPE_DOCUMENT: "Document",
    FILE_TYPE_IMAGE: "Image",
    FILE_TYPE_ARCHIVE: "Archive",
    FILE_TYPE_OTHER: "Other",
}


SUBSCRIPTION_LABELS = {
    SUBSCRIPTION_FREE: "Free",
    SUBSCRIPTION_PREMIUM: "Premium",
    SUBSCRIPTION_ADMIN: "Admin",
    SUBSCRIPTION_EXPIRED: "Expired",
    SUBSCRIPTION_CANCELLED: "Cancelled",
}


USER_STATUS_LABELS = {
    USER_STATUS_ACTIVE: "Active",
    USER_STATUS_INACTIVE: "Inactive",
    USER_STATUS_BANNED: "Banned",
    USER_STATUS_BLOCKED: "Blocked",
    USER_STATUS_DELETED: "Deleted",
    USER_STATUS_PENDING: "Pending",
}


PAYMENT_STATUS_LABELS = {
    PAYMENT_PENDING: "Pending",
    PAYMENT_PROCESSING: "Processing",
    PAYMENT_COMPLETED: "Completed",
    PAYMENT_FAILED: "Failed",
    PAYMENT_CANCELLED: "Cancelled",
    PAYMENT_REFUNDED: "Refunded",
}


# ============================================================================
# Export list
# ============================================================================

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_DESCRIPTION",
    "APP_AUTHOR",

    "ENV_DEVELOPMENT",
    "ENV_TESTING",
    "ENV_STAGING",
    "ENV_PRODUCTION",
    "VALID_ENVIRONMENTS",

    "DEFAULT_TIMEZONE",
    "DEFAULT_LANGUAGE",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MIN_PAGE_SIZE",

    "SEARCH_MIN_QUERY_LENGTH",
    "SEARCH_MAX_QUERY_LENGTH",
    "SEARCH_DEFAULT_SORT",
    "VALID_SORT_MODES",

    "FILE_TYPE_ANY",
    "FILE_TYPE_VIDEO",
    "FILE_TYPE_AUDIO",
    "FILE_TYPE_DOCUMENT",
    "FILE_TYPE_IMAGE",
    "FILE_TYPE_ARCHIVE",
    "FILE_TYPE_OTHER",
    "VALID_FILE_TYPES",

    "VIDEO_EXTENSIONS",
    "AUDIO_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "ARCHIVE_EXTENSIONS",

    "QUALITY_ANY",
    "QUALITY_CAM",
    "QUALITY_720P",
    "QUALITY_1080P",
    "QUALITY_2160P",
    "QUALITY_4K",
    "VALID_QUALITIES",
    "QUALITY_RANK",

    "LANGUAGE_ANY",
    "LANGUAGE_ENGLISH",
    "LANGUAGE_HINDI",
    "LANGUAGE_TELUGU",
    "LANGUAGE_TAMIL",
    "LANGUAGE_KANNADA",
    "LANGUAGE_MALAYALAM",
    "VALID_LANGUAGES",

    "ROLE_USER",
    "ROLE_MODERATOR",
    "ROLE_ADMIN",
    "ROLE_OWNER",
    "VALID_ROLES",

    "USER_STATUS_ACTIVE",
    "USER_STATUS_INACTIVE",
    "USER_STATUS_BANNED",
    "USER_STATUS_BLOCKED",
    "USER_STATUS_DELETED",
    "USER_STATUS_PENDING",
    "VALID_USER_STATUSES",

    "SUBSCRIPTION_FREE",
    "SUBSCRIPTION_PREMIUM",
    "SUBSCRIPTION_ADMIN",
    "SUBSCRIPTION_EXPIRED",
    "SUBSCRIPTION_CANCELLED",
    "VALID_SUBSCRIPTION_STATUSES",

    "PAYMENT_PENDING",
    "PAYMENT_PROCESSING",
    "PAYMENT_COMPLETED",
    "PAYMENT_FAILED",
    "PAYMENT_CANCELLED",
    "PAYMENT_REFUNDED",
    "VALID_PAYMENT_STATUSES",

    "VERIFICATION_PENDING",
    "VERIFICATION_VERIFIED",
    "VERIFICATION_EXPIRED",
    "VERIFICATION_FAILED",
    "VERIFICATION_BLOCKED",
    "VALID_VERIFICATION_STATUSES",

    "DELIVERY_PENDING",
    "DELIVERY_PROCESSING",
    "DELIVERY_COMPLETED",
    "DELIVERY_FAILED",
    "DELIVERY_EXPIRED",
    "DELIVERY_CANCELLED",
    "VALID_DELIVERY_STATUSES",

    "BROADCAST_PENDING",
    "BROADCAST_SCHEDULED",
    "BROADCAST_PROCESSING",
    "BROADCAST_PAUSED",
    "BROADCAST_COMPLETED",
    "BROADCAST_FAILED",
    "BROADCAST_CANCELLED",
    "VALID_BROADCAST_STATUSES",

    "MODERATION_WARN",
    "MODERATION_MUTE",
    "MODERATION_BAN",
    "MODERATION_UNBAN",
    "MODERATION_BLOCK",
    "MODERATION_UNBLOCK",
    "VALID_MODERATION_ACTIONS",

    "DB_POOL_MIN_SIZE",
    "DB_POOL_MAX_SIZE",
    "DB_CONNECTION_TIMEOUT_SECONDS",
    "DB_COMMAND_TIMEOUT_SECONDS",

    "CACHE_KEY_PREFIX",
    "CACHE_DEFAULT_TTL_SECONDS",

    "DEFAULT_RATE_LIMIT_REQUESTS",
    "DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
    "DEFAULT_RATE_LIMIT_BURST",

    "PAGINATION_FIRST_PAGE",
    "PAGINATION_DEFAULT_SIZE",
    "PAGINATION_MAX_SIZE",

    "CALLBACK_NAV",
    "CALLBACK_SEARCH",
    "CALLBACK_MOVIE",
    "CALLBACK_FILE",
    "CALLBACK_FILTER",
    "CALLBACK_PREMIUM",
    "CALLBACK_SETTINGS",
    "CALLBACK_VERIFICATION",
    "CALLBACK_ADMIN",
    "CALLBACK_MODERATION",
    "CALLBACK_BROADCAST",

    "CB_HOME",
    "CB_BACK",
    "CB_SEARCH",
    "CB_MOVIES",
    "CB_FILES",
    "CB_PREMIUM",
    "CB_SETTINGS",
    "CB_HELP",

    "TEXT_HOME",
    "TEXT_BACK",
    "TEXT_CANCEL",
    "TEXT_CONFIRM",
    "TEXT_SEARCH",
    "TEXT_FILTERS",
    "TEXT_SETTINGS",
    "TEXT_HELP",
    "TEXT_PREMIUM",
    "TEXT_FILES",
    "TEXT_MOVIES",
    "TEXT_ADMIN",

    "BYTES_PER_KB",
    "BYTES_PER_MB",
    "BYTES_PER_GB",
    "BYTES_PER_TB",
    "MAX_FILE_SIZE_BYTES",

    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "SECONDS_PER_WEEK",

    "FEATURE_SEARCH",
    "FEATURE_MOVIES",
    "FEATURE_FILE_DELIVERY",
    "FEATURE_PREMIUM",
    "FEATURE_VERIFICATION",
    "FEATURE_BROADCAST",
    "FEATURE_MODERATION",
    "FEATURE_SHORTENER",
    "FEATURE_INDEXER",

    "DEFAULT_FEATURES",

    "REQUIRED_PRODUCTION_ENV_VARS",

    "HEALTH_PATH",
    "READINESS_PATH",
    "LIVENESS_PATH",
    "METRICS_PATH",

    "QUEUE_DEFAULT",
    "QUEUE_SEARCH",
    "QUEUE_INDEXING",
    "QUEUE_DELIVERY",
    "QUEUE_BROADCAST",
    "QUEUE_NOTIFICATIONS",
    "QUEUE_CLEANUP",

    "JOB_PENDING",
    "JOB_RUNNING",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_CANCELLED",
    "JOB_RETRYING",
    "VALID_JOB_STATUSES",

    "FILE_TYPE_LABELS",
    "SUBSCRIPTION_LABELS",
    "USER_STATUS_LABELS",
    "PAYMENT_STATUS_LABELS",
]