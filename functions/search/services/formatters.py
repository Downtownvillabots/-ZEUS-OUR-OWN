"""
Size and text formatting utilities.
"""

from __future__ import annotations


def format_bytes(size_bytes: int) -> str:
    """Converts bytes to human-readable size string (Binary standard)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"
