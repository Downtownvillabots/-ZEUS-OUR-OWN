"""Compiled patterns used by the metadata parser."""
import re
YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)")
RESOLUTION = re.compile(r"(?<!\w)(2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|220p|144p)(?!\w)", re.I)
FOUR_K = re.compile(r"(?<!\w)4k(?!\w)", re.I)
CODEC = re.compile(r"(?<!\w)(x264|x265|h264|h265|hevc|av1|avc)(?!\w)", re.I)
QUALITY = re.compile(r"(?<!\w)(WEB[- .]?DL|WEBRip|BluRay|BDRip|HDRip|DVDRip|CAMRip|HDTV|REMUX|BRRip)(?!\w)", re.I)
SERIES = (
    re.compile(r"(?<!\w)s(?P<season>\d{1,2})[ ._-]*e(?P<episode>\d{1,4})(?!\w)", re.I),
    re.compile(r"(?<!\w)season[ ._-]*(?P<season>\d{1,2})[ ._-]*episode[ ._-]*(?P<episode>\d{1,4})(?!\w)", re.I),
)
LANGUAGES = {
    "mal": "Malayalam", "malayalam": "Malayalam", "ml": "Malayalam",
    "kan": "Kannada", "kannada": "Kannada", "kn": "Kannada",
    "tel": "Telugu", "telugu": "Telugu", "te": "Telugu",
    "tam": "Tamil", "tamil": "Tamil", "ta": "Tamil",
    "eng": "English", "english": "English", "en": "English",
    "hin": "Hindi", "hindi": "Hindi", "hi": "Hindi",
}
