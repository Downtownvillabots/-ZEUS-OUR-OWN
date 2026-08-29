from functions.media_indexing.metadata.parser import parse


def test_movie_metadata():
    item = parse("Karnan.2021.1080p.HEVC.TAM.mkv")
    assert item.title == "Karnan"
    assert item.year == 2021
    assert item.resolution == "1080p"
    assert item.codec == "HEVC"
    assert item.languages == ("Tamil",)
    assert item.is_series is False


def test_series_metadata():
    item = parse("My.Series.S02E12.1080p.TEL.mkv")
    assert item.is_series is True
    assert item.season == 2
    assert item.episode == 12


def test_username_noise():
    item = parse("@CinemaLokam.Karnan.2021.720p.TAM.mkv")
    assert "cinemalokam" not in item.normalized_title
    assert item.title == "Karnan"
