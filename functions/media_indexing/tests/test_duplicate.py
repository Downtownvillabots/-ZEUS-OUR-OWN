from functions.media_indexing.metadata.parser import parse
from functions.media_indexing.duplicate.policy import is_duplicate


def test_same_size_and_identity_metadata_is_duplicate():
    media = parse("Karnan.2021.1080p.TAM.mkv")
    candidate = {
        "file_unique_id": "different-or-missing",
        "file_size": 200_000_000,
        "normalized_title": media.normalized_title,
        "year": 2021,
        "resolution": "1080p",
        "quality": None,
        "languages": ["Tamil"],
        "season": None,
        "episode": None,
    }
    assert is_duplicate(
        media,
        candidate,
        file_size=200_000_000,
        file_unique_id=None,
    )


def test_same_size_different_title_is_not_duplicate():
    media = parse("Karnan.2021.1080p.TAM.mkv")
    candidate = {
        "file_unique_id": None,
        "file_size": 200_000_000,
        "normalized_title": "different movie",
        "year": 2021,
        "resolution": "1080p",
        "quality": None,
        "languages": ["Tamil"],
        "season": None,
        "episode": None,
    }
    assert not is_duplicate(media, candidate, file_size=200_000_000, file_unique_id=None)
