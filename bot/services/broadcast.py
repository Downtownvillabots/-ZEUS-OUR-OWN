"""
Broadcast Service
=================

Handles:

- User broadcasts
- Group broadcasts
- Combined broadcasts
- FloodWait retry handling
- Blocked/deleted/invalid user cleanup
- Invalid group cleanup
- Optional pinning
- Bounded concurrency
- Database-backed batch broadcasting
- Broadcast statistics
- Telegram-friendly reports

Handlers should NOT contain the actual broadcast logic.
They should validate the admin request and call this service.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    Sequence,
)

from pyrogram import Client
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)

from ..database.users import UserRepository
from ..database.groups import GroupRepository


logger = logging.getLogger(__name__)


# ============================================================
# DATA CLASSES
# ============================================================


@dataclass(slots=True)
class BroadcastStats:
    """
    Statistics for one broadcast operation.
    """

    attempted: int = 0
    sent: int = 0
    failed: int = 0
    blocked: int = 0
    deleted: int = 0
    invalid: int = 0
    flood_wait: int = 0
    skipped: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def unsuccessful(self) -> int:
        return (
            self.failed
            + self.blocked
            + self.deleted
            + self.invalid
            + self.flood_wait
        )

    @property
    def success_rate(self) -> float:
        if self.attempted <= 0:
            return 0.0

        return round(
            (self.sent / self.attempted) * 100,
            2,
        )


@dataclass(slots=True)
class DeliveryResult:
    """
    Result of sending to one destination.
    """

    success: bool
    status: str
    target_id: int
    error: str | None = None


# ============================================================
# BROADCAST SERVICE
# ============================================================


class BroadcastService:
    """
    Central broadcast manager.

    The service intentionally limits concurrency. Sending thousands
    of Telegram requests simultaneously is unsafe and can trigger
    FloodWaits.

    Default:

        concurrency = 10
        max_flood_retries = 3
    """

    def __init__(
        self,
        bot: Client,
        users: UserRepository,
        groups: GroupRepository,
        *,
        concurrency: int = 10,
        max_flood_retries: int = 3,
    ) -> None:

        self.bot = bot

        self.users = users
        self.groups = groups

        self.concurrency = max(
            1,
            int(concurrency),
        )

        self.max_flood_retries = max(
            0,
            int(max_flood_retries),
        )

    # ========================================================
    # NORMALIZATION
    # ========================================================

    @staticmethod
    def normalize_targets(
        targets: Iterable[int],
    ) -> list[int]:
        """
        Convert IDs to integers and remove duplicates.

        Invalid IDs are silently skipped.
        """

        normalized: list[int] = []
        seen: set[int] = set()

        for target in targets:

            try:
                target_id = int(target)

            except (
                TypeError,
                ValueError,
            ):
                continue

            if target_id in seen:
                continue

            seen.add(target_id)
            normalized.append(target_id)

        return normalized

    # ========================================================
    # FLOOD WAIT
    # ========================================================

    @staticmethod
    async def sleep_for_flood_wait(
        exc: FloodWait,
    ) -> None:
        """
        Sleep according to Telegram's FloodWait value.
        """

        seconds = getattr(
            exc,
            "value",
            None,
        )

        if seconds is None:
            seconds = getattr(
                exc,
                "x",
                1,
            )

        try:
            seconds = max(
                1,
                int(seconds),
            )

        except (
            TypeError,
            ValueError,
        ):
            seconds = 1

        logger.warning(
            "Telegram FloodWait received. "
            "Sleeping for %s seconds.",
            seconds,
        )

        await asyncio.sleep(seconds)

    # ========================================================
    # USER CLEANUP
    # ========================================================

    async def remove_user(
        self,
        user_id: int,
    ) -> None:
        """
        Remove an unreachable user from database.
        """

        try:
            await self.users.delete_user(
                int(user_id),
            )

        except Exception:
            logger.exception(
                "Unable to remove invalid user %s",
                user_id,
            )

    # ========================================================
    # GROUP CLEANUP
    # ========================================================

    async def remove_group(
        self,
        chat_id: int,
    ) -> None:
        """
        Remove an unreachable group from database.
        """

        try:
            await self.groups.delete_chat(
                int(chat_id),
            )

        except Exception:
            logger.exception(
                "Unable to remove invalid group %s",
                chat_id,
            )

    # ========================================================
    # SEND TO USER
    # ========================================================

    async def send_to_user(
        self,
        user_id: int,
        message: Any,
        *,
        pin: bool = False,
    ) -> DeliveryResult:
        """
        Copy a message to one user.

        Returns a DeliveryResult instead of raising Telegram errors.
        """

        user_id = int(user_id)

        for attempt in range(
            self.max_flood_retries + 1
        ):

            try:

                copied = await message.copy(
                    chat_id=user_id,
                )

                if pin:

                    try:

                        await copied.pin(
                            both_sides=True,
                        )

                    except Exception:

                        logger.debug(
                            "Unable to pin broadcast "
                            "for user %s",
                            user_id,
                            exc_info=True,
                        )

                return DeliveryResult(
                    success=True,
                    status="sent",
                    target_id=user_id,
                )

            # ------------------------------------------------
            # FLOOD WAIT
            # ------------------------------------------------

            except FloodWait as exc:

                if (
                    attempt
                    >= self.max_flood_retries
                ):

                    return DeliveryResult(
                        success=False,
                        status="flood_wait",
                        target_id=user_id,
                        error=str(exc),
                    )

                await self.sleep_for_flood_wait(
                    exc,
                )

            # ------------------------------------------------
            # DELETED USER
            # ------------------------------------------------

            except InputUserDeactivated as exc:

                await self.remove_user(
                    user_id,
                )

                return DeliveryResult(
                    success=False,
                    status="deleted",
                    target_id=user_id,
                    error=str(exc),
                )

            # ------------------------------------------------
            # BLOCKED USER
            # ------------------------------------------------

            except UserIsBlocked as exc:

                await self.remove_user(
                    user_id,
                )

                return DeliveryResult(
                    success=False,
                    status="blocked",
                    target_id=user_id,
                    error=str(exc),
                )

            # ------------------------------------------------
            # INVALID PEER
            # ------------------------------------------------

            except PeerIdInvalid as exc:

                await self.remove_user(
                    user_id,
                )

                return DeliveryResult(
                    success=False,
                    status="invalid",
                    target_id=user_id,
                    error=str(exc),
                )

            # ------------------------------------------------
            # UNKNOWN ERROR
            # ------------------------------------------------

            except Exception as exc:

                logger.warning(
                    "User broadcast failed "
                    "for %s: %s",
                    user_id,
                    exc,
                )

                return DeliveryResult(
                    success=False,
                    status="failed",
                    target_id=user_id,
                    error=str(exc),
                )

        return DeliveryResult(
            success=False,
            status="failed",
            target_id=user_id,
        )

    # ========================================================
    # SEND TO GROUP
    # ========================================================

    async def send_to_group(
        self,
        chat_id: int,
        message: Any,
        *,
        pin: bool = False,
    ) -> DeliveryResult:
        """
        Copy a message to one group/channel.
        """

        chat_id = int(chat_id)

        for attempt in range(
            self.max_flood_retries + 1
        ):

            try:

                copied = await message.copy(
                    chat_id=chat_id,
                )

                if pin:

                    try:

                        await copied.pin()

                    except Exception:

                        logger.debug(
                            "Unable to pin broadcast "
                            "in group %s",
                            chat_id,
                            exc_info=True,
                        )

                return DeliveryResult(
                    success=True,
                    status="sent",
                    target_id=chat_id,
                )

            # ------------------------------------------------
            # FLOOD WAIT
            # ------------------------------------------------

            except FloodWait as exc:

                if (
                    attempt
                    >= self.max_flood_retries
                ):

                    return DeliveryResult(
                        success=False,
                        status="flood_wait",
                        target_id=chat_id,
                        error=str(exc),
                    )

                await self.sleep_for_flood_wait(
                    exc,
                )

            # ------------------------------------------------
            # INVALID GROUP / NO ACCESS
            # ------------------------------------------------

            except (
                PeerIdInvalid,
                ChatAdminRequired,
            ) as exc:

                await self.remove_group(
                    chat_id,
                )

                return DeliveryResult(
                    success=False,
                    status="invalid",
                    target_id=chat_id,
                    error=str(exc),
                )

            # ------------------------------------------------
            # UNKNOWN ERROR
            # ------------------------------------------------

            except Exception as exc:

                logger.warning(
                    "Group broadcast failed "
                    "for %s: %s",
                    chat_id,
                    exc,
                )

                return DeliveryResult(
                    success=False,
                    status="failed",
                    target_id=chat_id,
                    error=str(exc),
                )

        return DeliveryResult(
            success=False,
            status="failed",
            target_id=chat_id,
        )

    # ========================================================
    # RECORD RESULT
    # ========================================================

    @staticmethod
    def record_result(
        stats: BroadcastStats,
        result: DeliveryResult,
    ) -> None:
        """
        Add one delivery result to aggregate statistics.
        """

        if result.success:

            stats.sent += 1
            return

        if result.status == "blocked":

            stats.blocked += 1

        elif result.status == "deleted":

            stats.deleted += 1

        elif result.status == "invalid":

            stats.invalid += 1

        elif result.status == "flood_wait":

            stats.flood_wait += 1

        else:

            stats.failed += 1

    # ========================================================
    # MERGE STATISTICS
    # ========================================================

    @staticmethod
    def merge_stats(
        destination: BroadcastStats,
        source: BroadcastStats,
    ) -> None:

        destination.attempted += source.attempted
        destination.sent += source.sent
        destination.failed += source.failed
        destination.blocked += source.blocked
        destination.deleted += source.deleted
        destination.invalid += source.invalid
        destination.flood_wait += source.flood_wait
        destination.skipped += source.skipped

    # ========================================================
    # GENERIC BROADCAST
    # ========================================================

    async def _broadcast(
        self,
        targets: Sequence[int],
        sender: Callable[
            ...,
            Awaitable[DeliveryResult],
        ],
        message: Any,
        *,
        pin: bool = False,
    ) -> BroadcastStats:
        """
        Generic bounded-concurrency broadcast.

        This is the core engine used by both user and group
        broadcasts.
        """

        target_ids = self.normalize_targets(
            targets,
        )

        stats = BroadcastStats(
            attempted=len(target_ids),
        )

        if not target_ids:
            return stats

        semaphore = asyncio.Semaphore(
            self.concurrency,
        )

        async def worker(
            target_id: int,
        ) -> None:

            async with semaphore:

                try:

                    result = await sender(
                        target_id,
                        message,
                        pin=pin,
                    )

                except Exception as exc:

                    logger.exception(
                        "Unexpected broadcast "
                        "worker error for %s",
                        target_id,
                    )

                    result = DeliveryResult(
                        success=False,
                        status="failed",
                        target_id=target_id,
                        error=str(exc),
                    )

                self.record_result(
                    stats,
                    result,
                )

        await asyncio.gather(
            *(
                worker(target_id)
                for target_id in target_ids
            )
        )

        return stats

    # ========================================================
    # EXPLICIT USER BROADCAST
    # ========================================================

    async def broadcast_users(
        self,
        user_ids: Sequence[int],
        message: Any,
        *,
        pin: bool = False,
    ) -> BroadcastStats:
        """
        Broadcast to explicitly supplied user IDs.
        """

        return await self._broadcast(
            user_ids,
            self.send_to_user,
            message,
            pin=pin,
        )

    # ========================================================
    # EXPLICIT GROUP BROADCAST
    # ========================================================

    async def broadcast_groups(
        self,
        chat_ids: Sequence[int],
        message: Any,
        *,
        pin: bool = False,
    ) -> BroadcastStats:
        """
        Broadcast to explicitly supplied group IDs.
        """

        return await self._broadcast(
            chat_ids,
            self.send_to_group,
            message,
            pin=pin,
        )

    # ========================================================
    # ALL USERS
    # ========================================================

    async def broadcast_all_users(
        self,
        message: Any,
        *,
        pin: bool = False,
        batch_size: int = 500,
    ) -> BroadcastStats:
        """
        Broadcast to every registered user.

        Users are processed in batches so a huge database does
        not have to be loaded into memory.
        """

        stats = BroadcastStats()

        batch: list[int] = []

        cursor = self.users.get_all_users()

        async for user in cursor:

            user_id = user.get(
                "id",
            )

            if user_id is None:

                stats.skipped += 1
                continue

            try:

                batch.append(
                    int(user_id),
                )

            except (
                TypeError,
                ValueError,
            ):

                stats.skipped += 1
                continue

            if len(batch) >= batch_size:

                partial = await self.broadcast_users(
                    batch,
                    message,
                    pin=pin,
                )

                self.merge_stats(
                    stats,
                    partial,
                )

                batch.clear()

        if batch:

            partial = await self.broadcast_users(
                batch,
                message,
                pin=pin,
            )

            self.merge_stats(
                stats,
                partial,
            )

        return stats

    # ========================================================
    # ALL GROUPS
    # ========================================================

    async def broadcast_all_groups(
        self,
        message: Any,
        *,
        pin: bool = False,
        batch_size: int = 200,
    ) -> BroadcastStats:
        """
        Broadcast to every registered group.
        """

        stats = BroadcastStats()

        batch: list[int] = []

        cursor = self.groups.get_all_chats()

        async for group in cursor:

            chat_id = group.get(
                "id",
            )

            if chat_id is None:

                stats.skipped += 1
                continue

            try:

                batch.append(
                    int(chat_id),
                )

            except (
                TypeError,
                ValueError,
            ):

                stats.skipped += 1
                continue

            if len(batch) >= batch_size:

                partial = await self.broadcast_groups(
                    batch,
                    message,
                    pin=pin,
                )

                self.merge_stats(
                    stats,
                    partial,
                )

                batch.clear()

        if batch:

            partial = await self.broadcast_groups(
                batch,
                message,
                pin=pin,
            )

            self.merge_stats(
                stats,
                partial,
            )

        return stats

    # ========================================================
    # BROADCAST EVERYWHERE
    # ========================================================

    async def broadcast_everywhere(
        self,
        message: Any,
        *,
        pin: bool = False,
        include_users: bool = True,
        include_groups: bool = True,
    ) -> dict[str, BroadcastStats]:
        """
        Broadcast to users and/or groups.
        """

        tasks: dict[
            str,
            asyncio.Task[BroadcastStats],
        ] = {}

        if include_users:

            tasks["users"] = asyncio.create_task(
                self.broadcast_all_users(
                    message,
                    pin=pin,
                )
            )

        if include_groups:

            tasks["groups"] = asyncio.create_task(
                self.broadcast_all_groups(
                    message,
                    pin=pin,
                )
            )

        if not tasks:
            return {}

        completed = await asyncio.gather(
            *tasks.values(),
        )

        return {
            name: result
            for name, result in zip(
                tasks.keys(),
                completed,
            )
        }

    # ========================================================
    # STOP / CANCEL SUPPORT
    # ========================================================

    async def broadcast_users_with_cancel(
        self,
        user_ids: Sequence[int],
        message: Any,
        *,
        pin: bool = False,
        cancel_event: asyncio.Event | None = None,
    ) -> BroadcastStats:
        """
        Broadcast to users while allowing the caller to cancel
        future deliveries.

        Already-running Telegram requests are allowed to finish.
        """

        target_ids = self.normalize_targets(
            user_ids,
        )

        stats = BroadcastStats(
            attempted=len(target_ids),
        )

        semaphore = asyncio.Semaphore(
            self.concurrency,
        )

        async def worker(
            target_id: int,
        ) -> None:

            if (
                cancel_event
                and cancel_event.is_set()
            ):

                stats.skipped += 1
                return

            async with semaphore:

                if (
                    cancel_event
                    and cancel_event.is_set()
                ):

                    stats.skipped += 1
                    return

                result = await self.send_to_user(
                    target_id,
                    message,
                    pin=pin,
                )

                self.record_result(
                    stats,
                    result,
                )

        await asyncio.gather(
            *(
                worker(target_id)
                for target_id in target_ids
            )
        )

        return stats

    # ========================================================
    # PROGRESS CALLBACK SUPPORT
    # ========================================================

    async def broadcast_users_with_progress(
        self,
        user_ids: Sequence[int],
        message: Any,
        *,
        pin: bool = False,
        progress_callback: (
            Callable[
                [BroadcastStats],
                Awaitable[None],
            ]
            | None
        ) = None,
    ) -> BroadcastStats:
        """
        Broadcast while optionally notifying the caller after
        each delivery.

        Useful for an admin progress message.
        """

        target_ids = self.normalize_targets(
            user_ids,
        )

        stats = BroadcastStats(
            attempted=len(target_ids),
        )

        semaphore = asyncio.Semaphore(
            self.concurrency,
        )

        async def worker(
            target_id: int,
        ) -> None:

            async with semaphore:

                try:

                    result = await self.send_to_user(
                        target_id,
                        message,
                        pin=pin,
                    )

                    self.record_result(
                        stats,
                        result,
                    )

                except Exception as exc:

                    logger.exception(
                        "Progress broadcast "
                        "worker failed for %s",
                        target_id,
                    )

                    stats.failed += 1

                if progress_callback:

                    try:

                        await progress_callback(
                            stats,
                        )

                    except Exception:

                        logger.exception(
                            "Broadcast progress "
                            "callback failed",
                        )

        await asyncio.gather(
            *(
                worker(target_id)
                for target_id in target_ids
            )
        )

        return stats

    # ========================================================
    # REPORT
    # ========================================================

    @staticmethod
    def format_report(
        stats: BroadcastStats,
        *,
        title: str = "Broadcast Report",
    ) -> str:
        """
        Create a Telegram HTML-formatted report.
        """

        return (
            f"<b>📢 {title}</b>\\n\\n"
            f"🎯 Attempted: "
            f"<code>{stats.attempted}</code>\\n"
            f"✅ Sent: "
            f"<code>{stats.sent}</code>\\n"
            f"❌ Failed: "
            f"<code>{stats.failed}</code>\\n"
            f"🚫 Blocked: "
            f"<code>{stats.blocked}</code>\\n"
            f"🗑 Deleted: "
            f"<code>{stats.deleted}</code>\\n"
            f"⚠️ Invalid: "
            f"<code>{stats.invalid}</code>\\n"
            f"⏳ FloodWait: "
            f"<code>{stats.flood_wait}</code>\\n"
            f"⏭ Skipped: "
            f"<code>{stats.skipped}</code>\\n"
            f"📈 Success Rate: "
            f"<code>{stats.success_rate}%</code>"
        )

    # ========================================================
    # COMBINED REPORT
    # ========================================================

    @staticmethod
    def format_combined_report(
        results: dict[str, BroadcastStats],
        *,
        title: str = "Broadcast Report",
    ) -> str:
        """
        Create a combined users/groups report.
        """

        lines = [
            f"<b>📢 {title}</b>",
            "",
        ]

        total = BroadcastStats()

        for name, stats in results.items():

            BroadcastService.merge_stats(
                total,
                stats,
            )

            lines.extend(
                [
                    f"<b>━━ {name.title()} ━━</b>",
                    "",
                    f"🎯 Attempted: "
                    f"<code>{stats.attempted}</code>",
                    f"✅ Sent: "
                    f"<code>{stats.sent}</code>",
                    f"❌ Failed: "
                    f"<code>{stats.failed}</code>",
                    f"🚫 Blocked: "
                    f"<code>{stats.blocked}</code>",
                    f"🗑 Deleted: "
                    f"<code>{stats.deleted}</code>",
                    f"⚠️ Invalid: "
                    f"<code>{stats.invalid}</code>",
                    f"⏳ FloodWait: "
                    f"<code>{stats.flood_wait}</code>",
                    f"⏭ Skipped: "
                    f"<code>{stats.skipped}</code>",
                    f"📈 Success Rate: "
                    f"<code>{stats.success_rate}%</code>",
                    "",
                ]
            )

        lines.extend(
            [
                "<b>━━ TOTAL ━━</b>",
                "",
                f"🎯 Attempted: "
                f"<code>{total.attempted}</code>",
                f"✅ Sent: "
                f"<code>{total.sent}</code>",
                f"❌ Failed: "
                f"<code>{total.failed}</code>",
                f"🚫 Blocked: "
                f"<code>{total.blocked}</code>",
                f"🗑 Deleted: "
                f"<code>{total.deleted}</code>",
                f"⚠️ Invalid: "
                f"<code>{total.invalid}</code>",
                f"⏳ FloodWait: "
                f"<code>{total.flood_wait}</code>",
                f"⏭ Skipped: "
                f"<code>{total.skipped}</code>",
                f"📈 Success Rate: "
                f"<code>{total.success_rate}%</code>",
            ]
        )

        return "\n".join(lines)

    # ========================================================
    # JSON-SAFE REPORT
    # ========================================================

    @staticmethod
    def serialize_report(
        results: dict[str, BroadcastStats],
    ) -> dict[str, dict[str, int]]:
        """
        Return broadcast statistics in a JSON-friendly format.
        """

        return {
            name: stats.to_dict()
            for name, stats in results.items()
        }


__all__ = [
    "BroadcastService",
    "BroadcastStats",
    "DeliveryResult",
]