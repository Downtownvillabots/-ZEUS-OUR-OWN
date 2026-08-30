"""
bot/handlers/premium.py

Premium / subscription handlers.

Responsibilities
----------------
- /premium
- /plan
- /premium_status
- Display available plans
- Display current subscription
- Premium callback UI
- Premium access checks
- Expiry information
- Database/service adapters

The actual payment provider and subscription persistence remain outside
this handler.

Expected architecture
---------------------
bot/database/
    Subscription/user persistence

bot/services/premium.py
    Subscription business logic

bot/handlers/premium.py
    Telegram UI + command routing
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

PREMIUM_CALLBACK_PREFIX = "premium"

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_INACTIVE = "inactive"
STATUS_CANCELLED = "cancelled"
STATUS_PENDING = "pending"

DEFAULT_CURRENCY = "INR"

DEFAULT_PLANS = [
    {
        "id": "monthly",
        "name": "Monthly",
        "duration_days": 30,
        "price": 99,
        "currency": DEFAULT_CURRENCY,
    },
    {
        "id": "quarterly",
        "name": "3 Months",
        "duration_days": 90,
        "price": 249,
        "currency": DEFAULT_CURRENCY,
    },
    {
        "id": "yearly",
        "name": "Yearly",
        "duration_days": 365,
        "price": 799,
        "currency": DEFAULT_CURRENCY,
    },
]


# ============================================================================
# Generic helpers
# ============================================================================

def escape_html(
    value: Any,
) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_number(
    value: Any,
) -> str:

    try:
        return f"{int(value):,}"
    except (
        TypeError,
        ValueError,
    ):
        return "0"


def get_database(
    client: Client,
):
    return getattr(
        client,
        "db",
        None,
    )


def get_premium_service(
    client: Client,
):
    """
    Return the premium service if configured.
    """

    service = getattr(
        client,
        "premium_service",
        None,
    )

    if service is not None:
        return service

    try:

        from bot.services import premium

        return premium

    except ImportError:

        return None


async def call_method(
    obj: Any,
    names: tuple[str, ...],
    *args,
    **kwargs,
):
    """
    Call the first compatible method.

    Returns:
        found, result
    """

    if obj is None:
        return False, None

    for name in names:

        method = getattr(
            obj,
            name,
            None,
        )

        if method is None:
            continue

        try:

            result = method(
                *args,
                **kwargs,
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            return True, result

        except Exception:

            logger.exception(
                "Method failed: %s",
                name,
            )

            return True, None

    return False, None


# ============================================================================
# Date helpers
# ============================================================================

def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def parse_datetime(
    value: Any,
) -> Optional[datetime]:
    """
    Normalize common datetime formats.
    """

    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):

        if value.tzinfo is None:

            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    if isinstance(
        value,
        (int, float),
    ):

        try:

            return datetime.fromtimestamp(
                value,
                tz=timezone.utc,
            )

        except (
            ValueError,
            OverflowError,
        ):

            return None

    if isinstance(
        value,
        str,
    ):

        value = value.strip()

        if not value:
            return None

        try:

            parsed = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )

            if parsed.tzinfo is None:

                parsed = parsed.replace(
                    tzinfo=timezone.utc
                )

            return parsed.astimezone(
                timezone.utc
            )

        except ValueError:

            return None

    return None


def format_datetime(
    value: Any,
) -> str:

    parsed = parse_datetime(
        value
    )

    if parsed is None:
        return "Unknown"

    return parsed.strftime(
        "%d %b %Y, %H:%M UTC"
    )


def remaining_time(
    expires_at: Any,
) -> str:

    expiry = parse_datetime(
        expires_at
    )

    if expiry is None:
        return "Unknown"

    seconds = int(
        (
            expiry
            - utc_now()
        ).total_seconds()
    )

    if seconds <= 0:
        return "Expired"

    days, remainder = divmod(
        seconds,
        86400,
    )

    hours, remainder = divmod(
        remainder,
        3600,
    )

    minutes, _ = divmod(
        remainder,
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

    if minutes and len(parts) < 2:
        parts.append(
            f"{minutes}m"
        )

    return " ".join(
        parts
    ) or "<1m"


# ============================================================================
# Subscription normalization
# ============================================================================

def normalize_subscription(
    value: Any,
) -> dict[str, Any]:
    """
    Normalize database/service subscription result.
    """

    if value is None:
        return {}

    if isinstance(
        value,
        dict,
    ):
        return dict(
            value
        )

    fields = (
        "user_id",
        "status",
        "plan",
        "plan_id",
        "expires_at",
        "started_at",
        "created_at",
        "duration_days",
        "payment_id",
        "provider",
        "amount",
        "currency",
        "auto_renew",
    )

    result = {}

    for field in fields:

        item = getattr(
            value,
            field,
            None,
        )

        if item is not None:
            result[field] = item

    return result


def subscription_is_active(
    subscription: dict[str, Any],
) -> bool:

    if not subscription:
        return False

    status = str(
        subscription.get(
            "status",
            "",
        )
    ).lower()

    if status in {
        STATUS_CANCELLED,
        STATUS_EXPIRED,
        STATUS_INACTIVE,
    }:
        return False

    expires_at = subscription.get(
        "expires_at"
    )

    if expires_at is not None:

        expiry = parse_datetime(
            expires_at
        )

        if expiry is not None:

            if expiry <= utc_now():
                return False

    return status in {
        "",
        STATUS_ACTIVE,
        STATUS_PENDING,
    } or bool(
        expires_at
    )


# ============================================================================
# Subscription lookup
# ============================================================================

async def get_subscription(
    client: Client,
    user_id: int,
) -> dict[str, Any]:
    """
    Get current subscription.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "get_subscription",
            "get_user_subscription",
            "get_premium",
            "get_status",
        ),
        user_id=int(
            user_id
        ),
    )

    if found and result is not None:

        return normalize_subscription(
            result
        )

    db = get_database(
        client
    )

    found, result = await call_method(
        db,
        (
            "get_subscription",
            "get_user_subscription",
            "get_premium",
            "get_premium_status",
        ),
        int(user_id),
    )

    if found:

        return normalize_subscription(
            result
        )

    # Fallback to user record.
    found, result = await call_method(
        db,
        (
            "get_user",
            "find_user",
            "get_user_by_id",
        ),
        int(user_id),
    )

    if found and result:

        user = (
            result
            if isinstance(
                result,
                dict,
            )
            else vars(result)
        )

        premium = user.get(
            "premium"
        )

        if isinstance(
            premium,
            dict,
        ):
            return normalize_subscription(
                premium
            )

        if user.get(
            "is_premium"
        ):

            return {
                "user_id": user_id,
                "status": STATUS_ACTIVE,
                "expires_at": user.get(
                    "premium_expires_at"
                ),
                "plan": user.get(
                    "premium_plan"
                ),
            }

    return {}


# ============================================================================
# Premium access check
# ============================================================================

async def is_premium(
    client: Client,
    user_id: int,
) -> bool:
    """
    Central premium access check.

    Other handlers should import this function instead of implementing
    their own premium logic.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "is_premium",
            "has_premium",
            "has_active_subscription",
        ),
        user_id=int(
            user_id
        ),
    )

    if found:

        return bool(
            result
        )

    subscription = await get_subscription(
        client,
        int(user_id),
    )

    return subscription_is_active(
        subscription
    )


async def require_premium(
    client: Client,
    message: Message,
) -> bool:
    """
    Handler-level premium gate.
    """

    user = message.from_user

    if user is None:
        return False

    if await is_premium(
        client,
        int(
            user.id
        ),
    ):
        return True

    await send_premium_required(
        message
    )

    return False


# ============================================================================
# Premium required UI
# ============================================================================

def premium_menu_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 View Plans",
                    callback_data=(
                        "premium:plans"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 My Subscription",
                    callback_data=(
                        "premium:status"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Close",
                    callback_data=(
                        "premium:close"
                    ),
                )
            ],
        ]
    )


async def send_premium_required(
    message: Message,
):
    await message.reply_text(
        "<b>💎 Premium Required</b>\n\n"
        "This feature is available to premium members.\n\n"
        "Upgrade your account to unlock premium features.",
        reply_markup=premium_menu_keyboard(),
    )


# ============================================================================
# Plan normalization
# ============================================================================

def normalize_plan(
    plan: Any,
) -> dict[str, Any]:

    if isinstance(
        plan,
        dict,
    ):
        return dict(
            plan
        )

    fields = (
        "id",
        "plan_id",
        "name",
        "title",
        "duration_days",
        "price",
        "amount",
        "currency",
        "description",
        "features",
    )

    result = {}

    for field in fields:

        value = getattr(
            plan,
            field,
            None,
        )

        if value is not None:
            result[field] = value

    if "id" not in result:

        result["id"] = result.get(
            "plan_id"
        )

    return result


async def get_plans(
    client: Client,
) -> list[dict[str, Any]]:
    """
    Retrieve configured premium plans.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "get_plans",
            "list_plans",
            "available_plans",
        ),
    )

    if found and result:

        if isinstance(
            result,
            dict,
        ):

            result = (
                result.get(
                    "plans"
                )
                or result.get(
                    "items"
                )
                or []
            )

        try:

            plans = [
                normalize_plan(
                    plan
                )
                for plan in result
            ]

            if plans:
                return plans

        except TypeError:
            pass

    # Database-backed plans.
    db = get_database(
        client
    )

    found, result = await call_method(
        db,
        (
            "get_premium_plans",
            "get_plans",
            "list_plans",
        ),
    )

    if found and result:

        try:

            plans = [
                normalize_plan(
                    plan
                )
                for plan in result
            ]

            if plans:
                return plans

        except TypeError:
            pass

    return [
        normalize_plan(
            plan
        )
        for plan in DEFAULT_PLANS
    ]


# ============================================================================
# Plan display helpers
# ============================================================================

def plan_id(
    plan: dict[str, Any],
) -> str:

    return str(
        plan.get(
            "id"
        )
        or plan.get(
            "plan_id"
        )
        or ""
    )


def plan_name(
    plan: dict[str, Any],
) -> str:

    return str(
        plan.get(
            "name"
        )
        or plan.get(
            "title"
        )
        or plan_id(
            plan
        )
        or "Premium Plan"
    )


def plan_price(
    plan: dict[str, Any],
) -> Any:

    return (
        plan.get(
            "price"
        )
        if plan.get(
            "price"
        ) is not None
        else plan.get(
            "amount",
            0,
        )
    )


def plan_currency(
    plan: dict[str, Any],
) -> str:

    return str(
        plan.get(
            "currency",
            DEFAULT_CURRENCY,
        )
    )


def plan_duration(
    plan: dict[str, Any],
) -> str:

    days = plan.get(
        "duration_days"
    )

    if days is None:
        return "Flexible"

    try:
        days = int(
            days
        )
    except (
        TypeError,
        ValueError,
    ):
        return str(
            days
        )

    if days >= 365:

        years = days / 365

        if years.is_integer():
            return (
                f"{int(years)} year"
                f"{'s' if years != 1 else ''}"
            )

    if days >= 30:

        months = days / 30

        if months.is_integer():
            return (
                f"{int(months)} month"
                f"{'s' if months != 1 else ''}"
            )

    return (
        f"{days} day"
        f"{'s' if days != 1 else ''}"
    )


# ============================================================================
# Plan keyboard
# ============================================================================

def build_plans_keyboard(
    plans: list[dict[str, Any]],
) -> InlineKeyboardMarkup:

    rows = []

    for plan in plans:

        identifier = plan_id(
            plan
        )

        if not identifier:
            continue

        name = plan_name(
            plan
        )

        price = plan_price(
            plan
        )

        currency = plan_currency(
            plan
        )

        rows.append(
            [
                InlineKeyboardButton(
                    (
                        f"💎 {name} — "
                        f"{currency} {price}"
                    ),
                    callback_data=(
                        f"premium:plan:{identifier}"
                    ),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "📊 My Subscription",
                callback_data=(
                    "premium:status"
                ),
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data=(
                    "premium:close"
                ),
            )
        ]
    )

    return InlineKeyboardMarkup(
        rows
    )


# ============================================================================
# Plans page
# ============================================================================

async def show_plans(
    client: Client,
    message: Message,
):
    """
    Show premium plans.
    """

    plans = await get_plans(
        client
    )

    if not plans:

        await message.reply_text(
            "<b>💎 Premium</b>\n\n"
            "No premium plans are currently available."
        )

        return

    lines = [
        "<b>💎 Premium Plans</b>",
        "",
        "Choose the plan that works best for you.",
        "",
    ]

    for plan in plans:

        lines.append(
            f"<b>💎 {escape_html(plan_name(plan))}</b>"
        )

        lines.append(
            f"⏱️ Duration: "
            f"{escape_html(plan_duration(plan))}"
        )

        lines.append(
            f"💰 Price: "
            f"<b>{escape_html(plan_currency(plan))} "
            f"{escape_html(plan_price(plan))}</b>"
        )

        description = plan.get(
            "description"
        )

        if description:

            lines.append(
                escape_html(
                    description
                )
            )

        lines.append("")

    await message.reply_text(
        "\n".join(
            lines
        ),
        reply_markup=build_plans_keyboard(
            plans
        ),
    )


# ============================================================================
# /premium
# ============================================================================

async def premium_command(
    client: Client,
    message: Message,
):
    await show_premium_home(
        client,
        message,
    )


async def show_premium_home(
    client: Client,
    message: Message,
):
    """
    Premium landing page.
    """

    user = message.from_user

    if user is None:
        return

    subscription = await get_subscription(
        client,
        int(
            user.id
        ),
    )

    active = subscription_is_active(
        subscription
    )

    if active:

        status_text = (
            "🟢 <b>Premium Active</b>"
        )

        expiry = subscription.get(
            "expires_at"
        )

        if expiry:

            status_text += (
                f"\n⏳ Remaining: "
                f"<b>{escape_html(remaining_time(expiry))}</b>"
            )

    else:

        status_text = (
            "⚪ <b>Free Account</b>"
        )

    text = (
        "<b>💎 Premium</b>\n\n"
        f"{status_text}\n\n"
        "Premium can unlock additional features, "
        "higher limits, and a better experience."
    )

    await message.reply_text(
        text,
        reply_markup=premium_menu_keyboard(),
    )


# ============================================================================
# /plan
# ============================================================================

async def plan_command(
    client: Client,
    message: Message,
):
    await show_plans(
        client,
        message,
    )


# ============================================================================
# /premium_status
# ============================================================================

async def premium_status_command(
    client: Client,
    message: Message,
):
    await show_subscription(
        client,
        message,
    )


# ============================================================================
# Subscription UI
# ============================================================================

def subscription_status_label(
    subscription: dict[str, Any],
) -> str:

    if not subscription:
        return "⚪ Free"

    if subscription_is_active(
        subscription
    ):
        return "🟢 Active"

    status = str(
        subscription.get(
            "status",
            "",
        )
    ).lower()

    if status == STATUS_CANCELLED:
        return "🟠 Cancelled"

    if status == STATUS_PENDING:
        return "🟡 Pending"

    return "🔴 Expired"


async def show_subscription(
    client: Client,
    message: Message,
):
    """
    Show current subscription.
    """

    user = message.from_user

    if user is None:
        return

    subscription = await get_subscription(
        client,
        int(
            user.id
        ),
    )

    active = subscription_is_active(
        subscription
    )

    if not subscription or not active:

        text = (
            "<b>📊 My Subscription</b>\n\n"
            "Plan: <b>Free</b>\n"
            "Status: <b>Inactive</b>\n\n"
            "You currently do not have an active premium subscription."
        )

        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💎 View Plans",
                            callback_data=(
                                "premium:plans"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Close",
                            callback_data=(
                                "premium:close"
                            ),
                        )
                    ],
                ]
            ),
        )

        return

    plan = (
        subscription.get(
            "plan"
        )
        or subscription.get(
            "plan_id"
        )
        or "Premium"
    )

    expires_at = subscription.get(
        "expires_at"
    )

    started_at = subscription.get(
        "started_at"
    )

    auto_renew = subscription.get(
        "auto_renew"
    )

    text = (
        "<b>📊 My Subscription</b>\n\n"
        f"💎 Plan: "
        f"<b>{escape_html(plan)}</b>\n"
        f"📌 Status: "
        f"<b>{subscription_status_label(subscription)}</b>\n"
        f"📅 Started: "
        f"<b>{escape_html(format_datetime(started_at))}</b>\n"
        f"⏳ Expires: "
        f"<b>{escape_html(format_datetime(expires_at))}</b>\n"
        f"⌛ Remaining: "
        f"<b>{escape_html(remaining_time(expires_at))}</b>"
    )

    if auto_renew is not None:

        text += (
            "\n🔄 Auto-renew: "
            f"<b>{'Enabled' if auto_renew else 'Disabled'}</b>"
        )

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💎 Change Plan",
                        callback_data=(
                            "premium:plans"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Close",
                        callback_data=(
                            "premium:close"
                        ),
                    )
                ],
            ]
        ),
    )


# ============================================================================
# Plan callback
# ============================================================================

async def plan_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Display selected plan.
    """

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        "premium:plan:"
    )

    if not data.startswith(
        prefix
    ):
        return

    identifier = data[
        len(prefix):
    ]

    if not identifier:

        await callback_query.answer(
            "Invalid plan.",
            show_alert=True,
        )

        return

    plans = await get_plans(
        client
    )

    selected = None

    for plan in plans:

        if plan_id(
            plan
        ) == identifier:

            selected = plan
            break

    if selected is None:

        await callback_query.answer(
            "Plan no longer exists.",
            show_alert=True,
        )

        return

    name = plan_name(
        selected
    )

    price = plan_price(
        selected
    )

    currency = plan_currency(
        selected
    )

    duration = plan_duration(
        selected
    )

    description = selected.get(
        "description"
    )

    features = selected.get(
        "features"
    )

    lines = [
        "<b>💎 Premium Plan</b>",
        "",
        f"📦 Plan: <b>{escape_html(name)}</b>",
        f"⏱️ Duration: <b>{escape_html(duration)}</b>",
        f"💰 Price: <b>{escape_html(currency)} {escape_html(price)}</b>",
    ]

    if description:

        lines.extend(
            [
                "",
                escape_html(
                    description
                ),
            ]
        )

    if features:

        lines.extend(
            [
                "",
                "<b>✨ Features</b>",
            ]
        )

        try:

            for feature in features:

                lines.append(
                    f"• {escape_html(feature)}"
                )

        except TypeError:
            pass

    lines.extend(
        [
            "",
            "Continue to payment to activate this plan.",
        ]
    )

    await callback_query.answer()

    if callback_query.message:

        await callback_query.message.edit_text(
            "\n".join(
                lines
            ),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💳 Continue",
                            callback_data=(
                                f"premium:buy:{identifier}"
                            ),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⬅️ Plans",
                            callback_data=(
                                "premium:plans"
                            ),
                        )
                    ],
                ]
            ),
        )


# ============================================================================
# Purchase
# ============================================================================

async def create_purchase(
    client: Client,
    user_id: int,
    plan: dict[str, Any],
) -> Any:
    """
    Ask premium/payment service to create a purchase.

    Payment implementation is intentionally delegated.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "create_purchase",
            "create_checkout",
            "start_checkout",
            "buy_plan",
        ),
        user_id=int(
            user_id
        ),
        plan=plan,
        plan_id=plan_id(
            plan
        ),
    )

    if found:
        return result

    return None


def extract_payment_url(
    result: Any,
) -> Optional[str]:

    if result is None:
        return None

    if isinstance(
        result,
        str,
    ):

        if result.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return result

        return None

    if isinstance(
        result,
        dict,
    ):

        for key in (
            "url",
            "checkout_url",
            "payment_url",
            "invoice_url",
            "link",
        ):

            value = result.get(
                key
            )

            if value:
                return str(
                    value
                )

    for key in (
        "url",
        "checkout_url",
        "payment_url",
        "invoice_url",
        "link",
    ):

        value = getattr(
            result,
            key,
            None,
        )

        if value:
            return str(
                value
            )

    return None


# ============================================================================
# Buy callback
# ============================================================================

async def buy_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Start purchase flow.
    """

    user = callback_query.from_user

    if user is None:
        return

    data = (
        callback_query.data
        or ""
    )

    prefix = (
        "premium:buy:"
    )

    if not data.startswith(
        prefix
    ):
        return

    identifier = data[
        len(prefix):
    ]

    plans = await get_plans(
        client
    )

    selected = None

    for plan in plans:

        if plan_id(
            plan
        ) == identifier:

            selected = plan
            break

    if selected is None:

        await callback_query.answer(
            "Plan unavailable.",
            show_alert=True,
        )

        return

    await callback_query.answer(
        "⏳ Creating payment..."
    )

    result = await create_purchase(
        client,
        int(
            user.id
        ),
        selected,
    )

    payment_url = extract_payment_url(
        result
    )

    if payment_url:

        await show_payment_link(
            callback_query,
            selected,
            payment_url,
        )

        return

    # If no payment provider is configured yet.
    if callback_query.message:

        await callback_query.message.edit_text(
            "<b>💳 Payment</b>\n\n"
            "The selected plan is ready, but the payment provider "
            "has not been configured yet.\n\n"
            "Please contact the administrator.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Plans",
                            callback_data=(
                                "premium:plans"
                            ),
                        )
                    ]
                ]
            ),
        )


async def show_payment_link(
    callback_query: CallbackQuery,
    plan: dict[str, Any],
    payment_url: str,
):
    """
    Render payment URL.

    URL itself is kept inside Telegram's inline keyboard rather than
    being exposed as callback data.
    """

    if callback_query.message is None:
        return

    await callback_query.message.edit_text(
        "<b>💳 Complete Payment</b>\n\n"
        f"Plan: <b>{escape_html(plan_name(plan))}</b>\n"
        f"Price: <b>{escape_html(plan_currency(plan))} "
        f"{escape_html(plan_price(plan))}</b>\n\n"
        "Tap the button below to continue.\n\n"
        "After successful payment, your premium status will be updated.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💳 Pay Now",
                        url=payment_url,
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 Check Status",
                        callback_data=(
                            "premium:status"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Plans",
                        callback_data=(
                            "premium:plans"
                        ),
                    )
                ],
            ]
        ),
    )


# ============================================================================
# Status callback
# ============================================================================

async def status_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Show current premium status.
    """

    user = callback_query.from_user

    if user is None:
        return

    subscription = await get_subscription(
        client,
        int(
            user.id
        ),
    )

    await callback_query.answer()

    if callback_query.message is None:
        return

    if not subscription or not subscription_is_active(
        subscription
    ):

        text = (
            "<b>📊 My Subscription</b>\n\n"
            "⚪ <b>Free</b>\n\n"
            "No active premium subscription."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💎 View Plans",
                        callback_data=(
                            "premium:plans"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Close",
                        callback_data=(
                            "premium:close"
                        ),
                    )
                ],
            ]
        )

    else:

        plan = (
            subscription.get(
                "plan"
            )
            or subscription.get(
                "plan_id"
            )
            or "Premium"
        )

        expiry = subscription.get(
            "expires_at"
        )

        text = (
            "<b>📊 My Subscription</b>\n\n"
            "🟢 <b>Premium Active</b>\n\n"
            f"💎 Plan: <b>{escape_html(plan)}</b>\n"
            f"⏳ Remaining: "
            f"<b>{escape_html(remaining_time(expiry))}</b>\n"
            f"📅 Expires: "
            f"<b>{escape_html(format_datetime(expiry))}</b>"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💎 Change Plan",
                        callback_data=(
                            "premium:plans"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Close",
                        callback_data=(
                            "premium:close"
                        ),
                    )
                ],
            ]
        )

    try:

        await callback_query.message.edit_text(
            text,
            reply_markup=keyboard,
        )

    except Exception:

        logger.exception(
            "Unable to render premium status"
        )


# ============================================================================
# Plans callback
# ============================================================================

async def plans_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    """
    Display plans from callback.
    """

    plans = await get_plans(
        client
    )

    await callback_query.answer()

    if callback_query.message is None:
        return

    lines = [
        "<b>💎 Premium Plans</b>",
        "",
        "Choose your plan:",
        "",
    ]

    for plan in plans:

        lines.extend(
            [
                f"<b>{escape_html(plan_name(plan))}</b>",
                f"⏱️ {escape_html(plan_duration(plan))}",
                f"💰 {escape_html(plan_currency(plan))} "
                f"{escape_html(plan_price(plan))}",
                "",
            ]
        )

    try:

        await callback_query.message.edit_text(
            "\n".join(
                lines
            ),
            reply_markup=build_plans_keyboard(
                plans
            ),
        )

    except Exception:

        logger.exception(
            "Unable to display premium plans"
        )


# ============================================================================
# Close callback
# ============================================================================

async def close_callback(
    client: Client,
    callback_query: CallbackQuery,
):
    await callback_query.answer()

    if callback_query.message:

        try:

            await callback_query.message.delete()

        except Exception:

            try:

                await callback_query.message.edit_reply_markup(
                    reply_markup=None
                )

            except Exception:
                pass


# ============================================================================
# Premium activation
# ============================================================================

async def activate_subscription(
    client: Client,
    user_id: int,
    plan_id_value: str,
    payment_id: Optional[str] = None,
) -> bool:
    """
    Activate a premium subscription.

    This is normally called by the payment/webhook layer, not by the user
    directly.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "activate_subscription",
            "activate",
            "grant_premium",
            "activate_premium",
        ),
        user_id=int(
            user_id
        ),
        plan_id=plan_id_value,
        payment_id=payment_id,
    )

    if found:
        return bool(
            result
        )

    db = get_database(
        client
    )

    found, result = await call_method(
        db,
        (
            "activate_subscription",
            "activate_premium",
            "grant_premium",
        ),
        int(user_id),
        plan_id_value,
        payment_id,
    )

    if found:
        return bool(
            result
        )

    return False


# ============================================================================
# Manual admin grant adapter
# ============================================================================

async def grant_premium(
    client: Client,
    user_id: int,
    plan_id_value: str,
) -> bool:
    """
    Grant premium through the configured service/database.

    Admin command can use this function later.
    """

    return await activate_subscription(
        client,
        user_id,
        plan_id_value,
    )


# ============================================================================
# Expiry processing
# ============================================================================

async def expire_subscription(
    client: Client,
    user_id: int,
) -> bool:
    """
    Mark subscription expired.

    Usually invoked by a scheduled worker.
    """

    service = get_premium_service(
        client
    )

    found, result = await call_method(
        service,
        (
            "expire_subscription",
            "expire",
            "remove_premium",
        ),
        user_id=int(
            user_id
        ),
    )

    if found:
        return bool(
            result
        )

    db = get_database(
        client
    )

    found, result = await call_method(
        db,
        (
            "expire_subscription",
            "expire_premium",
            "remove_premium",
        ),
        int(user_id),
    )

    if found:
        return bool(
            result
        )

    return False


# ============================================================================
# Callback registration
# ============================================================================

def register(
    app: Client,
):
    """
    Explicit registration.

    Use this OR Pyrogram plugin discovery, not both.
    """

    from pyrogram.handlers import (
        MessageHandler,
        CallbackQueryHandler,
    )

    app.add_handler(
        MessageHandler(
            premium_command,
            filters.command(
                "premium"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            plan_command,
            filters.command(
                "plan"
            ),
        )
    )

    app.add_handler(
        MessageHandler(
            premium_status_command,
            filters.command(
                "premium_status"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            plans_callback,
            filters.regex(
                r"^premium:plans$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            plan_callback,
            filters.regex(
                r"^premium:plan:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_callback,
            filters.regex(
                r"^premium:buy:"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            status_callback,
            filters.regex(
                r"^premium:status$"
            ),
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            close_callback,
            filters.regex(
                r"^premium:close$"
            ),
        )
    )

    logger.info(
        "Registered premium handlers"
    )


# ============================================================================
# Pyrogram plugin handlers
# ============================================================================

@Client.on_message(
    filters.command(
        "premium"
    )
)
async def premium_handler(
    client: Client,
    message: Message,
):
    await premium_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "plan"
    )
)
async def plan_handler(
    client: Client,
    message: Message,
):
    await plan_command(
        client,
        message,
    )


@Client.on_message(
    filters.command(
        "premium_status"
    )
)
async def premium_status_handler(
    client: Client,
    message: Message,
):
    await premium_status_command(
        client,
        message,
    )


@Client.on_callback_query(
    filters.regex(
        r"^premium:plans$"
    )
)
async def premium_plans_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await plans_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^premium:plan:"
    )
)
async def premium_plan_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await plan_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^premium:buy:"
    )
)
async def premium_buy_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await buy_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^premium:status$"
    )
)
async def premium_status_callback_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await status_callback(
        client,
        callback_query,
    )


@Client.on_callback_query(
    filters.regex(
        r"^premium:close$"
    )
)
async def premium_close_handler(
    client: Client,
    callback_query: CallbackQuery,
):
    await close_callback(
        client,
        callback_query,
    )


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    "get_subscription",
    "is_premium",
    "require_premium",
    "get_plans",
    "show_plans",
    "show_subscription",
    "activate_subscription",
    "grant_premium",
    "expire_subscription",
    "premium_command",
    "plan_command",
    "premium_status_command",
    "register",
]