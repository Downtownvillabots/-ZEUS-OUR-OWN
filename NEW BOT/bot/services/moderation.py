"""
Moderation service for the new bot.

Keeps Telegram moderation/admin logic outside handlers.

Features carried forward from the old bot:
- User ban/unban
- Group disable/enable
- Ban status lookup
- Admin verification
- Safe Telegram exception handling
- Cleanup of invalid users/chats
- Bulk broadcast helpers
- Cooperative FloodWait handling

Handlers should call these methods rather than directly changing MongoDB
documents or duplicating Pyrogram exception handling.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

from pyrogram import Client, enums
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)

from ..database.users import UserRepository
from ..database.groups import GroupRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModerationResult:
    success: bool
    action: str
    target_id: int
    reason: str = ""
    error: Optional[str] = None


@dataclass(slots=True)
class BroadcastResult:
    attempted: int = 0
    success: int = 0
    deleted: int = 0
    blocked: int = 0
    invalid: int = 0
    flood_waits: int = 0
    errors: int = 0


class ModerationService:
    def __init__(
        self,
        bot: Client,
        users: UserRepository,
        groups: GroupRepository,
    ) -> None:
        self.bot = bot
        self.users = users
        self.groups = groups

    # ------------------------------------------------------------------
    # Admin / membership
    # ------------------------------------------------------------------

    async def is_admin(
        self,
        chat_id: int,
        user_id: int,
    ) -> bool:
        """Return True when the user is an owner or administrator."""
        try:
            member = await self.bot.get_chat_member(
                int(chat_id),
                int(user_id),
            )

            return member.status in {
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            }

        except Exception:
            return False

    async def is_member(
        self,
        chat_id: int,
        user_id: int,
    ) -> bool:
        """Check whether a user can be considered a member of a chat."""
        try:
            member = await self.bot.get_chat_member(
                int(chat_id),
                int(user_id),
            )

            return member.status not in {
                enums.ChatMemberStatus.LEFT,
                enums.ChatMemberStatus.BANNED,
            }

        except UserNotParticipant:
            return False
        except Exception:
            return False

    async def is_banned(
        self,
        chat_id: int,
        user_id: int,
    ) -> bool:
        try:
            member = await self.bot.get_chat_member(
                int(chat_id),
                int(user_id),
            )
            return member.status == enums.ChatMemberStatus.BANNED
        except Exception:
            return False

    # ------------------------------------------------------------------
    # User moderation
    # ------------------------------------------------------------------

    async def ban_user(
        self,
        user_id: int,
        reason: str = "No Reason",
    ) -> ModerationResult:
        user_id = int(user_id)

        try:
            await self.users.ban_user(
                user_id,
                reason=reason,
            )

            return ModerationResult(
                success=True,
                action="ban_user",
                target_id=user_id,
                reason=reason,
            )

        except Exception as exc:
            logger.exception(
                "Failed banning user %s",
                user_id,
            )

            return ModerationResult(
                success=False,
                action="ban_user",
                target_id=user_id,
                reason=reason,
                error=str(exc),
            )

    async def unban_user(
        self,
        user_id: int,
    ) -> ModerationResult:
        user_id = int(user_id)

        try:
            await self.users.remove_ban(user_id)

            return ModerationResult(
                success=True,
                action="unban_user",
                target_id=user_id,
            )

        except Exception as exc:
            logger.exception(
                "Failed unbanning user %s",
                user_id,
            )

            return ModerationResult(
                success=False,
                action="unban_user",
                target_id=user_id,
                error=str(exc),
            )

    async def get_user_ban_status(
        self,
        user_id: int,
    ) -> dict[str, Any]:
        return await self.users.get_ban_status(int(user_id))

    async def is_user_banned(
        self,
        user_id: int,
    ) -> bool:
        status = await self.get_user_ban_status(user_id)
        return bool(status.get("is_banned", False))

    # ------------------------------------------------------------------
    # Group moderation
    # ------------------------------------------------------------------

    async def disable_group(
        self,
        chat_id: int,
        reason: str = "No Reason",
    ) -> ModerationResult:
        chat_id = int(chat_id)

        try:
            await self.groups.disable_chat(
                chat_id,
                reason=reason,
            )

            return ModerationResult(
                success=True,
                action="disable_group",
                target_id=chat_id,
                reason=reason,
            )

        except Exception as exc:
            logger.exception(
                "Failed disabling group %s",
                chat_id,
            )

            return ModerationResult(
                success=False,
                action="disable_group",
                target_id=chat_id,
                reason=reason,
                error=str(exc),
            )

    async def enable_group(
        self,
        chat_id: int,
    ) -> ModerationResult:
        chat_id = int(chat_id)

        try:
            await self.groups.re_enable_chat(chat_id)

            return ModerationResult(
                success=True,
                action="enable_group",
                target_id=chat_id,
            )

        except Exception as exc:
            logger.exception(
                "Failed enabling group %s",
                chat_id,
            )

            return ModerationResult(
                success=False,
                action="enable_group",
                target_id=chat_id,
                error=str(exc),
            )

    async def get_group_status(
        self,
        chat_id: int,
    ) -> dict[str, Any] | bool:
        return await self.groups.get_chat(int(chat_id))

    async def is_group_disabled(
        self,
        chat_id: int,
    ) -> bool:
        status = await self.get_group_status(chat_id)

        if status is False or not status:
            return False

        return bool(status.get("is_disabled", False))

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    async def cleanup_user(
        self,
        user_id: int,
    ) -> None:
        try:
            await self.users.delete_user(int(user_id))
        except Exception:
            logger.exception(
                "Failed cleaning user %s",
                user_id,
            )

    async def cleanup_group(
        self,
        chat_id: int,
    ) -> None:
        try:
            await self.groups.delete_chat(int(chat_id))
        except Exception:
            logger.exception(
                "Failed cleaning group %s",
                chat_id,
            )

    # ------------------------------------------------------------------
    # User broadcast
    # ------------------------------------------------------------------

    async def broadcast_user(
        self,
        user_id: int,
        message: Any,
        *,
        pin: bool = False,
        max_retries: int = 3,
    ) -> tuple[bool, str]:
        """
        Copy a message to one user.

        FloodWait is retried. Deleted, blocked and invalid users are removed
        from the active user repository.
        """
        user_id = int(user_id)

        for attempt in range(max_retries + 1):
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
                            "Unable to pin broadcast for %s",
                            user_id,
                            exc_info=True,
                        )

                return True, "Success"

            except FloodWait as exc:
                if attempt >= max_retries:
                    return False, "FloodWait"

                await asyncio.sleep(
                    max(1, int(exc.value)),
                )

            except InputUserDeactivated:
                await self.cleanup_user(user_id)
                return False, "Deleted"

            except UserIsBlocked:
                await self.cleanup_user(user_id)
                return False, "Blocked"

            except PeerIdInvalid:
                await self.cleanup_user(user_id)
                return False, "Invalid"

            except Exception as exc:
                logger.debug(
                    "User broadcast failed for %s: %s",
                    user_id,
                    exc,
                )
                return False, "Error"

        return False, "Error"

    async def broadcast_users(
        self,
        user_ids: list[int],
        message: Any,
        *,
        pin: bool = False,
        concurrency: int = 10,
    ) -> BroadcastResult:
        """Broadcast to users with bounded concurrency."""
        result = BroadcastResult(
            attempted=len(user_ids),
        )

        semaphore = asyncio.Semaphore(
            max(1, int(concurrency)),
        )

        async def send_one(user_id: int) -> None:
            async with semaphore:
                ok, status = await self.broadcast_user(
                    user_id,
                    message,
                    pin=pin,
                )

                if ok:
                    result.success += 1
                elif status == "Deleted":
                    result.deleted += 1
                elif status == "Blocked":
                    result.blocked += 1
                elif status == "Invalid":
                    result.invalid += 1
                elif status == "FloodWait":
                    result.flood_waits += 1
                else:
                    result.errors += 1

        await asyncio.gather(
            *(send_one(user_id) for user_id in user_ids)
        )

        return result

    # ------------------------------------------------------------------
    # Group broadcast
    # ------------------------------------------------------------------

    async def broadcast_group(
        self,
        chat_id: int,
        message: Any,
        *,
        pin: bool = False,
        max_retries: int = 3,
    ) -> tuple[bool, str]:
        """Copy a message to one group/channel."""
        chat_id = int(chat_id)

        for attempt in range(max_retries + 1):
            try:
                copied = await message.copy(
                    chat_id=chat_id,
                )

                if pin:
                    try:
                        await copied.pin()
                    except Exception:
                        logger.debug(
                            "Unable to pin group broadcast in %s",
                            chat_id,
                            exc_info=True,
                        )

                return True, "Success"

            except FloodWait as exc:
                if attempt >= max_retries:
                    return False, "FloodWait"

                await asyncio.sleep(
                    max(1, int(exc.value)),
                )

            except (PeerIdInvalid, ChatAdminRequired):
                await self.cleanup_group(chat_id)
                return False, "Invalid"

            except Exception as exc:
                logger.debug(
                    "Group broadcast failed for %s: %s",
                    chat_id,
                    exc,
                )
                return False, "Error"

        return False, "Error"

    async def broadcast_groups(
        self,
        chat_ids: list[int],
        message: Any,
        *,
        pin: bool = False,
        concurrency: int = 5,
    ) -> BroadcastResult:
        """Broadcast to groups with bounded concurrency."""
        result = BroadcastResult(
            attempted=len(chat_ids),
        )

        semaphore = asyncio.Semaphore(
            max(1, int(concurrency)),
        )

        async def send_one(chat_id: int) -> None:
            async with semaphore:
                ok, status = await self.broadcast_group(
                    chat_id,
                    message,
                    pin=pin,
                )

                if ok:
                    result.success += 1
                elif status == "FloodWait":
                    result.flood_waits += 1
                elif status == "Invalid":
                    result.invalid += 1
                else:
                    result.errors += 1

        await asyncio.gather(
            *(send_one(chat_id) for chat_id in chat_ids)
        )

        return result

    # ------------------------------------------------------------------
    # Junk message cleanup
    # ------------------------------------------------------------------

    async def copy_and_delete(
        self,
        target_id: int,
        message: Any,
        *,
        max_retries: int = 3,
    ) -> tuple[bool, str, str]:
        """
        Copy a temporary/junk message and immediately delete the copy.

        Kept as a service because the old bot used this pattern while
        validating Telegram access.
        """
        target_id = int(target_id)

        for attempt in range(max_retries + 1):
            try:
                copied = await message.copy(
                    chat_id=target_id,
                )

                try:
                    await copied.delete(
                        revoke=True,
                    )
                except TypeError:
                    await copied.delete()

                return True, "Success", ""

            except FloodWait as exc:
                if attempt >= max_retries:
                    return False, "FloodWait", str(exc)

                await asyncio.sleep(
                    max(1, int(exc.value)),
                )

            except InputUserDeactivated:
                await self.cleanup_user(target_id)
                return False, "Deleted", "InputUserDeactivated"

            except UserIsBlocked:
                await self.cleanup_user(target_id)
                return False, "Blocked", "UserIsBlocked"

            except PeerIdInvalid as exc:
                await self.cleanup_user(target_id)
                return False, "Invalid", str(exc)

            except Exception as exc:
                return False, "Error", str(exc)

        return False, "Error", ""

    # ------------------------------------------------------------------
    # Group junk cleanup
    # ------------------------------------------------------------------

    async def cleanup_group_message(
        self,
        chat_id: int,
        message: Any,
        *,
        max_retries: int = 3,
    ) -> tuple[bool, str]:
        chat_id = int(chat_id)

        for attempt in range(max_retries + 1):
            try:
                copied = await message.copy(
                    chat_id=chat_id,
                )

                try:
                    await copied.delete(
                        revoke=True,
                    )
                except TypeError:
                    await copied.delete()

                return True, "Success"

            except FloodWait as exc:
                if attempt >= max_retries:
                    return False, "FloodWait"

                await asyncio.sleep(
                    max(1, int(exc.value)),
                )

            except Exception:
                await self.cleanup_group(chat_id)
                return False, "Error"

        return False, "Error"

    # ------------------------------------------------------------------
    # Bulk status
    # ------------------------------------------------------------------

    async def get_moderation_snapshot(self) -> dict[str, Any]:
        """
        Get the current user/group moderation state.

        Repository methods intentionally remain responsible for persistence.
        """
        banned_users, disabled_groups = await self.users.get_banned()

        return {
            "banned_users": banned_users,
            "disabled_groups": disabled_groups,
            "banned_user_count": len(banned_users),
            "disabled_group_count": len(disabled_groups),
        }


__all__ = [
    "ModerationService",
    "ModerationResult",
    "BroadcastResult",
]
