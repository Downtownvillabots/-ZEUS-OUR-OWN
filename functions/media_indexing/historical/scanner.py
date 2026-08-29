"""Backward scanner for Telegram channel history.

The scanner is deliberately independent of MongoDB. It yields messages in
older-to-oldest direction from the selected starting point.
"""
from __future__ import annotations


async def scan_backward(client, chat_id: int, start_message_id: int, limit: int = 1_000_000):
    current = int(start_message_id)
    scanned = 0
    while current > 0 and scanned < limit:
        count = min(100, limit - scanned)
        messages = []
        async for message in client.get_chat_history(
            chat_id,
            limit=count,
            offset_id=current,
        ):
            messages.append(message)

        if not messages:
            return

        progressed = False
        for message in messages:
            if message.id >= current:
                continue
            progressed = True
            current = message.id
            scanned += 1
            yield message
            if scanned >= limit:
                return

        if not progressed:
            return
