"""
bot.database.models

Core database models.

Entities
--------
User
Group
File
FileRequest
PremiumSubscription
Verification
UserSettings
GroupSettings
BotSettings

The models intentionally contain business state only.
Database connection/session management belongs in connection.py.

The schema is designed around PostgreSQL/SQLAlchemy-style persistence,
but the models remain usable as plain Python dataclasses as well.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ============================================================================
# Time helpers
# ============================================================================

def utcnow() -> datetime:
    """
    Return a timezone-aware UTC datetime.
    """

    return datetime.now(
        timezone.utc
    )


# ============================================================================
# Base model
# ============================================================================

class ModelMixin:
    """
    Common helpers shared by all models.
    """

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return asdict(
            self
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ):
        return cls(
            **data
        )


# ============================================================================
# Enumerations
# ============================================================================

class UserStatus(str, Enum):

    ACTIVE = "active"

    BANNED = "banned"

    BLOCKED = "blocked"

    DISABLED = "disabled"

    DELETED = "deleted"


class UserRole(str, Enum):

    USER = "user"

    MODERATOR = "moderator"

    ADMIN = "admin"

    OWNER = "owner"


class GroupStatus(str, Enum):

    ACTIVE = "active"

    DISABLED = "disabled"

    LEFT = "left"

    DELETED = "deleted"


class FileStatus(str, Enum):

    ACTIVE = "active"

    DELETED = "deleted"

    EXPIRED = "expired"

    BLOCKED = "blocked"


class RequestStatus(str, Enum):

    PENDING = "pending"

    PROCESSING = "processing"

    COMPLETED = "completed"

    FAILED = "failed"

    CANCELLED = "cancelled"


class PremiumStatus(str, Enum):

    ACTIVE = "active"

    EXPIRED = "expired"

    CANCELLED = "cancelled"

    REVOKED = "revoked"


class VerificationStatus(str, Enum):

    PENDING = "pending"

    VERIFIED = "verified"

    EXPIRED = "expired"

    FAILED = "failed"

    REVOKED = "revoked"


# ============================================================================
# User
# ============================================================================

@dataclass
class User(ModelMixin):

    id: int

    username: Optional[str] = None

    first_name: Optional[str] = None

    last_name: Optional[str] = None

    language_code: Optional[str] = None

    is_bot: bool = False

    status: UserStatus = (
        UserStatus.ACTIVE
    )

    role: UserRole = (
        UserRole.USER
    )

    is_admin: bool = False

    is_premium: bool = False

    is_verified: bool = False

    premium_until: Optional[
        datetime
    ] = None

    verification_until: Optional[
        datetime
    ] = None

    ban_reason: Optional[str] = None

    last_seen_at: Optional[
        datetime
    ] = None

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def is_banned(
        self,
    ) -> bool:

        return self.status in {
            UserStatus.BANNED,
            UserStatus.BLOCKED,
        }

    @property
    def display_name(
        self,
    ) -> str:

        parts = [
            self.first_name,
            self.last_name,
        ]

        value = " ".join(
            part
            for part in parts
            if part
        )

        if value:
            return value

        if self.username:
            return f"@{self.username}"

        return str(
            self.id
        )

    def mark_seen(
        self,
    ) -> None:

        now = utcnow()

        self.last_seen_at = now

        self.updated_at = now

    def ban(
        self,
        reason: Optional[str] = None,
    ) -> None:

        self.status = (
            UserStatus.BANNED
        )

        self.ban_reason = reason

        self.updated_at = utcnow()

    def unban(
        self,
    ) -> None:

        self.status = (
            UserStatus.ACTIVE
        )

        self.ban_reason = None

        self.updated_at = utcnow()


# ============================================================================
# Group
# ============================================================================

@dataclass
class Group(ModelMixin):

    id: int

    title: Optional[str] = None

    username: Optional[str] = None

    group_type: Optional[str] = None

    status: GroupStatus = (
        GroupStatus.ACTIVE
    )

    is_enabled: bool = True

    is_verified: bool = False

    member_count: Optional[int] = None

    added_by: Optional[int] = None

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def display_name(
        self,
    ) -> str:

        if self.title:
            return self.title

        if self.username:
            return f"@{self.username}"

        return str(
            self.id
        )


# ============================================================================
# File
# ============================================================================

@dataclass
class File(ModelMixin):

    id: Optional[int] = None

    telegram_file_id: Optional[
        str
    ] = None

    telegram_unique_id: Optional[
        str
    ] = None

    file_name: Optional[str] = None

    mime_type: Optional[str] = None

    file_size: Optional[int] = None

    file_type: Optional[str] = None

    status: FileStatus = (
        FileStatus.ACTIVE
    )

    message_id: Optional[int] = None

    chat_id: Optional[int] = None

    owner_id: Optional[int] = None

    caption: Optional[str] = None

    checksum: Optional[str] = None

    storage_key: Optional[str] = None

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    expires_at: Optional[
        datetime
    ] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def is_expired(
        self,
    ) -> bool:

        if self.expires_at is None:
            return False

        return utcnow() >= self.expires_at

    @property
    def is_available(
        self,
    ) -> bool:

        return (
            self.status
            == FileStatus.ACTIVE
            and not self.is_expired
        )


# ============================================================================
# File request
# ============================================================================

@dataclass
class FileRequest(ModelMixin):

    id: Optional[int] = None

    user_id: int = 0

    group_id: Optional[int] = None

    query: Optional[str] = None

    requested_file_id: Optional[
        int
    ] = None

    status: RequestStatus = (
        RequestStatus.PENDING
    )

    result_count: int = 0

    selected_file_id: Optional[
        int
    ] = None

    error_message: Optional[
        str
    ] = None

    request_type: str = "search"

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    completed_at: Optional[
        datetime
    ] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def complete(
        self,
        *,
        selected_file_id: Optional[
            int
        ] = None,
        result_count: Optional[
            int
        ] = None,
    ) -> None:

        self.status = (
            RequestStatus.COMPLETED
        )

        if selected_file_id is not None:

            self.selected_file_id = (
                selected_file_id
            )

        if result_count is not None:

            self.result_count = (
                result_count
            )

        self.completed_at = utcnow()

        self.updated_at = utcnow()

    def fail(
        self,
        message: str,
    ) -> None:

        self.status = (
            RequestStatus.FAILED
        )

        self.error_message = (
            message
        )

        self.updated_at = utcnow()


# ============================================================================
# Premium subscription
# ============================================================================

@dataclass
class PremiumSubscription(ModelMixin):

    id: Optional[int] = None

    user_id: int = 0

    plan: str = "premium"

    status: PremiumStatus = (
        PremiumStatus.ACTIVE
    )

    started_at: datetime = field(
        default_factory=utcnow
    )

    expires_at: Optional[
        datetime
    ] = None

    cancelled_at: Optional[
        datetime
    ] = None

    payment_provider: Optional[
        str
    ] = None

    payment_reference: Optional[
        str
    ] = None

    amount: Optional[float] = None

    currency: Optional[str] = None

    auto_renew: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def is_active(
        self,
    ) -> bool:

        if self.status != (
            PremiumStatus.ACTIVE
        ):

            return False

        if self.expires_at is None:

            return True

        return utcnow() < self.expires_at

    def expire(
        self,
    ) -> None:

        self.status = (
            PremiumStatus.EXPIRED
        )


# ============================================================================
# Verification
# ============================================================================

@dataclass
class Verification(ModelMixin):

    id: Optional[int] = None

    user_id: int = 0

    status: VerificationStatus = (
        VerificationStatus.PENDING
    )

    token_hash: Optional[str] = None

    challenge_type: str = "default"

    attempts: int = 0

    max_attempts: int = 5

    created_at: datetime = field(
        default_factory=utcnow
    )

    verified_at: Optional[
        datetime
    ] = None

    expires_at: Optional[
        datetime
    ] = None

    last_attempt_at: Optional[
        datetime
    ] = None

    failure_reason: Optional[
        str
    ] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def is_verified(
        self,
    ) -> bool:

        return (
            self.status
            == VerificationStatus.VERIFIED
        )

    @property
    def is_expired(
        self,
    ) -> bool:

        if self.expires_at is None:
            return False

        return utcnow() >= self.expires_at

    @property
    def attempts_remaining(
        self,
    ) -> int:

        return max(
            0,
            self.max_attempts
            - self.attempts,
        )

    def mark_verified(
        self,
    ) -> None:

        self.status = (
            VerificationStatus.VERIFIED
        )

        self.verified_at = utcnow()

        self.failure_reason = None

    def register_attempt(
        self,
    ) -> None:

        self.attempts += 1

        self.last_attempt_at = (
            utcnow()
        )


# ============================================================================
# User settings
# ============================================================================

@dataclass
class UserSettings(ModelMixin):

    user_id: int

    language: str = "en"

    notifications_enabled: bool = True

    auto_delete_files: bool = False

    auto_delete_seconds: int = 0

    preferred_quality: Optional[
        str
    ] = None

    preferred_format: Optional[
        str
    ] = None

    safe_search: bool = True

    search_limit: int = 10

    result_page_size: int = 10

    show_file_size: bool = True

    compact_results: bool = False

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# Group settings
# ============================================================================

@dataclass
class GroupSettings(ModelMixin):

    group_id: int

    enabled: bool = True

    search_enabled: bool = True

    file_delivery_enabled: bool = True

    verification_required: bool = False

    premium_only: bool = False

    auto_delete_files: bool = False

    auto_delete_seconds: int = 0

    rate_limit_enabled: bool = True

    welcome_enabled: bool = True

    logging_enabled: bool = True

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# Bot settings
# ============================================================================

@dataclass
class BotSettings(ModelMixin):

    key: str

    value: Any = None

    description: Optional[str] = None

    is_secret: bool = False

    updated_by: Optional[int] = None

    created_at: datetime = field(
        default_factory=utcnow
    )

    updated_at: datetime = field(
        default_factory=utcnow
    )


# ============================================================================
# Generic audit event
# ============================================================================

@dataclass
class AuditEvent(ModelMixin):

    id: Optional[int] = None

    user_id: Optional[int] = None

    group_id: Optional[int] = None

    action: str = ""

    target_type: Optional[str] = None

    target_id: Optional[str] = None

    success: bool = True

    reason: Optional[str] = None

    created_at: datetime = field(
        default_factory=utcnow
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# Model registry
# ============================================================================

MODEL_REGISTRY: dict[
    str,
    type[ModelMixin],
] = {
    "user": User,
    "group": Group,
    "file": File,
    "request": FileRequest,
    "premium": PremiumSubscription,
    "verification": Verification,
    "user_settings": UserSettings,
    "group_settings": GroupSettings,
    "bot_settings": BotSettings,
    "audit_event": AuditEvent,
}


def get_model(
    name: str,
) -> type[ModelMixin]:

    normalized = (
        str(name)
        .strip()
        .lower()
    )

    try:

        return MODEL_REGISTRY[
            normalized
        ]

    except KeyError:

        raise ValueError(
            f"Unknown model: {name}"
        )


def list_models() -> list[str]:

    return list(
        MODEL_REGISTRY.keys()
    )


# ============================================================================
# Serialization
# ============================================================================

def serialize_model(
    model: ModelMixin,
) -> dict[str, Any]:

    return model.to_dict()


def deserialize_model(
    name: str,
    data: dict[str, Any],
) -> ModelMixin:

    model_class = get_model(
        name
    )

    return model_class.from_dict(
        data
    )


# ============================================================================
# Validation helpers
# ============================================================================

def validate_user_id(
    user_id: Any,
) -> int:

    try:

        value = int(
            user_id
        )

    except (
        TypeError,
        ValueError,
    ):

        raise ValueError(
            "user_id must be an integer."
        )

    if value <= 0:

        raise ValueError(
            "user_id must be greater than zero."
        )

    return value


def validate_group_id(
    group_id: Any,
) -> int:

    try:

        value = int(
            group_id
        )

    except (
        TypeError,
        ValueError,
    ):

        raise ValueError(
            "group_id must be an integer."
        )

    if value == 0:

        raise ValueError(
            "group_id cannot be zero."
        )

    return value


def validate_file_size(
    size: Optional[int],
) -> Optional[int]:

    if size is None:
        return None

    try:

        value = int(
            size
        )

    except (
        TypeError,
        ValueError,
    ):

        raise ValueError(
            "file_size must be an integer."
        )

    if value < 0:

        raise ValueError(
            "file_size cannot be negative."
        )

    return value


# ============================================================================
# Public exports
# ============================================================================

__all__ = [
    "utcnow",

    "ModelMixin",

    "UserStatus",
    "UserRole",
    "GroupStatus",
    "FileStatus",
    "RequestStatus",
    "PremiumStatus",
    "VerificationStatus",

    "User",
    "Group",
    "File",
    "FileRequest",
    "PremiumSubscription",
    "Verification",
    "UserSettings",
    "GroupSettings",
    "BotSettings",
    "AuditEvent",

    "MODEL_REGISTRY",
    "get_model",
    "list_models",

    "serialize_model",
    "deserialize_model",

    "validate_user_id",
    "validate_group_id",
    "validate_file_size",
]