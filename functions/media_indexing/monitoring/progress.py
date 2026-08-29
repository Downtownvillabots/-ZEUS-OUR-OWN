"""
Live Progress Bar and ETA Monitor.
"""

from __future__ import annotations

import time


class ProgressMonitor:
    @staticmethod
    def render_cube(completed: int, total: int, width: int = 10) -> str:
        if total <= 0:
            return "⬜" * width
        filled = int(round(min(1.0, max(0.0, completed / total)) * width))
        return "🟩" * filled + "⬜" * (width - filled)

    @classmethod
    def format_status(
        cls, mode: str, scanned: int, total: int, added: int, duplicates: int,
        series_skipped: int, unsupported: int, errors: int, start_time: float,
        active_db: str, db_usage_mb: float, target_mb: float,
    ) -> str:
        elapsed = max(0.1, time.time() - start_time)
        speed = scanned / elapsed
        percent = int((scanned / total) * 100) if total > 0 else 0
        eta_seconds = int((total - scanned) / speed) if speed > 0 and total > scanned else 0

        hours, remainder = divmod(eta_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        eta_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"

        return (
            f"🏙️ **DOWNTOWN VILLA — INDEXER**\n\n"
            f"🎬 **MODE:** {mode}\n\n"
            f"{cls.render_cube(scanned, total)}  {percent}%\n\n"
            f"📁 **Scanned:** {scanned:,} / {total:,}\n"
            f"✅ **Added:** {added:,}\n"
            f"⏭️ **Duplicates:** {duplicates:,}\n"
            f"📺 **Series skipped:** {series_skipped:,}\n"
            f"⚪ **Unsupported:** {unsupported:,}\n"
            f"❌ **Errors:** {errors:,}\n\n"
            f"⚡ **Speed:** {speed:.1f} files/sec\n"
            f"💾 **Active DB:** {active_db}\n"
            f"📦 **DB usage:** {int(db_usage_mb)} / {int(target_mb)} MB\n"
            f"⏱️ **ETA:** {eta_str}"
        )
