"""
Configuration for Search Intelligence and Movie Request / BIN System.
"""

import os

# Request BIN Channel ID from environment
REQUEST_BIN_CHANNEL_ID: int = int(os.getenv("REQUEST_BIN_CHANNEL_ID", "0"))

# External API Timeout (Seconds) - Prevents search blocking
IMDB_TIMEOUT_SECONDS: float = 3.0

# List of Admin Telegram User IDs (Can be loaded from config/env)
ADMIN_USER_IDS: list[int] = [
    int(uid.strip()) for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip().isdigit()
]
