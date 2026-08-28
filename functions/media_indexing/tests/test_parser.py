from functions.media_indexing.metadata.parser import parse


def test_movie():
    m = parse("Karnan.2021.1080p.HEVC.TAM.mkv")
    assert m.title == "Karnan"
    assert m.year == 2021
    assert m.resolution == "1080p"
    assert m.is_series is False


def test_series():
    m = parse("Some.Series.S02E12.1080p.TEL.mkv")
    assert m.season == 2
    assert m.episode == 12
    assert m.is_series is True
