"""Progress counters for one indexing operation."""
from dataclasses import dataclass

@dataclass(slots=True)
class IndexProgress:
    scanned: int = 0
    saved: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: int = 0
