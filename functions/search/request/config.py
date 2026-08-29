"""
Configuration for Search Intelligence and Movie Request / BIN System.
"""

import os

REQUEST_BIN_CHANNEL_ID: int = int(os.getenv("REQUEST_BIN_CHANNEL_ID", "0"))
IMDB_TIMEOUT_SECONDS: float = 3.0

ADMIN_USER_IDS: list[int] = [
    int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip().isdigit()
]
