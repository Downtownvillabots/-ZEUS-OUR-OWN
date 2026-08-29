"""Human-readable progress formatting."""
from __future__ import annotations
from time import monotonic


class ProgressReporter:
    def __init__(self):
        self.started = monotonic()

    def rate(self, scanned: int) -> float:
        elapsed = max(monotonic() - self.started, 0.001)
        return scanned / elapsed

    def text(self, stats) -> str:
        return (
            "🏙️ DOWNTOWN VILLA INDEXER\n"
            f"📁 Scanned: {stats.scanned:,}\n"
            f"✅ Saved: {stats.saved:,}\n"
            f"⏭️ Duplicates: {stats.duplicates:,}\n"
            f"🚫 Filtered: {stats.filtered:,}\n"
            f"❌ Errors: {stats.errors:,}\n"
            f"⚡ Rate: {self.rate(stats.scanned):.2f} files/s"
        )
