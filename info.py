import re
import os
from os import environ, getenv
from Script import script

# Utility functions
id_pattern = re.compile(r'^.\d+$')

def is_enabled(value, default):
    if value is None:
        return default
    value = str(value).strip().lower()
    if value in ["true", "yes", "1", "enable", "y"]:
        return True
    elif value in ["false", "no", "0", "disable", "n"]:
        return False
    else:
        return default

# ============================
# Downtown Villa Branding
# ============================
BOT_NAME = environ.get('BOT_NAME', 'DOWNTOWN VILLA')
BOT_LINK = environ.get('BOT_LINK', 'https://t.me/DownTownVillaBot')
BRAND_NAME = environ.get('BRAND_NAME', 'DOWNTOWN VILLA')
BRAND_LOGO = environ.get('BRAND_LOGO', 'https://example.com/logo.png')

# ============================
# Bot Information Configuration
# ============================
SESSION = environ.get('SESSION', 'down_town_villa_search')
API_ID = int(environ.get('API_ID', ''))
API_HASH = environ.get('API_HASH', '')
BOT_TOKEN = environ.get('BOT_TOKEN', "")

# ============================
# Bot Settings Configuration
# ============================
CACHE_TIME = int(environ.get('CACHE_TIME', 300))
USE_CAPTION_FILTER = is_enabled(environ.get('USE_CAPTION_FILTER', "True"), True)
INDEX_CAPTION = is_enabled(environ.get('SAVE_CAPTION', "True"), True)
COVERX = is_enabled(environ.get('COVERX', "True"), True)

PICS_URL = (environ.get('PICS', 'https://api.aniwallpaper.workers.dev/random?type=girl')).split()
PICS = (environ.get('PICS', 'https://graph.org/file/56b5deb73f3b132e2bb73.jpg https://graph.org/file/5303692652d91d52180c2.jpg')).split()
NOR_IMG = environ.get("NOR_IMG", "https://graph.org/file/e20b5fdaf217252964202.jpg")
MELCOW_PHOTO = environ.get("MELCOW_PHOTO", "https://graph.org/file/56b5deb73f3b132e2bb73.jpg")
SPELL_IMG = environ.get("SPELL_IMG", "https://graph.org/file/13702ae26fb05df52667c.jpg")
SUBSCRIPTION = (environ.get('SUBSCRIPTION', 'https://graph.org/file/242b7f1b52743938d81f1.jpg'))
FSUB_PICS = (environ.get('FSUB_PICS', 'https://graph.org/file/7478ff3eac37f4329c3d8.jpg https://graph.org/file/56b5deb73f3b132e2bb73.jpg')).split()

# ============================
# Admin, Channels & Users
# ============================
ADMINS = [int(admin) if id_pattern.search(admin) else admin for admin in environ.get('ADMINS', '634637418').split()]
CHANNELS = [int(ch) if id_pattern.search(ch) else ch for ch in environ.get('CHANNELS', '-100').split()]
LOG_CHANNEL = int(environ.get('LOG_CHANNEL', '-100'))
BIN_CHANNEL = int(environ.get('BIN_CHANNEL', '-100'))
PREMIUM_LOGS = int(environ.get('PREMIUM_LOGS', '-100'))
DELETE_CHANNELS = [int(dch) if id_pattern.search(dch) else dch for dch in environ.get('DELETE_CHANNELS', '-100').split()]
support_chat_id = environ.get('SUPPORT_CHAT_ID', '-100')
reqst_channel = environ.get('REQST_CHANNEL_ID', '-100')
SUPPORT_CHAT = environ.get('SUPPORT_CHAT', 'https://t.me/DownTownVillaSupport')

# FORCE_SUB
auth_req_channels = environ.get("AUTH_REQ_CHANNELS", "-100")
auth_channels     = environ.get("AUTH_CHANNELS", "-100")

# ============================
# Payment Configuration
# ============================
QR_CODE = environ.get('QR_CODE', 'https://graph.org/file/e419f801841c2ee3db0fc.jpg')
OWNER_UPI_ID = environ.get('OWNER_UPI_ID', 'not_set')

STAR_PREMIUM_PLANS = {
    10: "7day",
    20: "15day",
    40: "1month",
    55: "45day",
    75: "60day",
}

# ============================
# MongoDB Configuration – Unlimited DB Support
# ============================
USER_DATABASE = environ.get('USER_DATABASE', environ.get('DATABASE_URI', ''))   # user DB URI (users/groups/settings)
DATABASE_NAME = environ.get('DATABASE_NAME', "Cluster0")
COLLECTION_NAME = environ.get('COLLECTION_NAME', 'downtown_villa_files')

# Collect all MEDIA database URIs from DATABASE_URI_1, DATABASE_URI_2, ...
_uri_1 = environ.get('DATABASE_URI_1', '')
_uri_2 = environ.get('DATABASE_URI_2', '')
_uri_3 = environ.get('DATABASE_URI_3', '')
_uri_4 = environ.get('DATABASE_URI_4', '')
_uri_5 = environ.get('DATABASE_URI_5', '')
_uri_6 = environ.get('DATABASE_URI_6', '')
_uri_7 = environ.get('DATABASE_URI_7', '')
_uri_8 = environ.get('DATABASE_URI_8', '')
_uri_9 = environ.get('DATABASE_URI_9', '')
_uri_10 = environ.get('DATABASE_URI_10', '')

_ALL_URIS = [
    _uri_1, _uri_2, _uri_3, _uri_4, _uri_5,
    _uri_6, _uri_7, _uri_8, _uri_9, _uri_10
]

# Filter out empty or duplicate URIs
MEDIA_DATABASE_URIS = []
_seen = set()
for uri in _ALL_URIS:
    if uri and uri not in _seen:
        MEDIA_DATABASE_URIS.append(uri)
        _seen.add(uri)

# If no media DBs are set, fall back to the user DB (optional, but better to error if missing)
if not MEDIA_DATABASE_URIS:
    if USER_DATABASE:
        MEDIA_DATABASE_URIS = [USER_DATABASE]   # fallback: use the same DB if no media DB provided
    else:
        MEDIA_DATABASE_URIS = ['mongodb://localhost:27017']   # placeholder to avoid crash

# Determine if multiple media DBs are enabled
MULTIPLE_DB = len(MEDIA_DATABASE_URIS) > 1 or is_enabled(environ.get('MULTIPLE_DB', "False"), False)

# For backward compatibility (old code may still import DATABASE_URI) – but we are removing it
# Do NOT define DATABASE_URI here – remove all references to it in the project.


# ============================
# Movie Notification & Update Settings
# ============================
MOVIE_UPDATE_NOTIFICATION = is_enabled(environ.get('MOVIE_UPDATE_NOTIFICATION', "False"), False)
MOVIE_UPDATE_CHANNEL = int(environ.get('MOVIE_UPDATE_CHANNEL', '-100'))
DREAMXBOTZ_IMAGE_FETCH = is_enabled(environ.get('DREAMXBOTZ_IMAGE_FETCH', "True"), True)
LINK_PREVIEW = is_enabled(environ.get('LINK_PREVIEW', "False"), False)
ABOVE_PREVIEW = is_enabled(environ.get('ABOVE_PREVIEW', "True"), True)
TMDB_API_KEY = environ.get('TMDB_API_KEY', '')
TMDB_POSTER = is_enabled(environ.get('TMDB_POSTER', "True"), True)
LANDSCAPE_POSTER = is_enabled(environ.get('LANDSCAPE_POSTER', "True"), True)

# ============================
# Verification Settings
# ============================
IS_VERIFY = is_enabled(environ.get('IS_VERIFY', 'False'), False)
LOG_VR_CHANNEL = int(environ.get('LOG_VR_CHANNEL', '-100'))
LOG_API_CHANNEL = int(environ.get('LOG_API_CHANNEL', '-100'))
VERIFY_IMG = environ.get("VERIFY_IMG", "https://telegra.ph/file/9ecc5d6e4df5b83424896.jpg")

TUTORIAL = environ.get("TUTORIAL", "https://t.me/DownTownVilla")
TUTORIAL_2 = environ.get("TUTORIAL_2", "https://t.me/DownTownVilla")
TUTORIAL_3 = environ.get("TUTORIAL_3", "https://t.me/DownTownVilla")

SHORTENER_API = environ.get("SHORTENER_API", "")
SHORTENER_WEBSITE = environ.get("SHORTENER_WEBSITE", "")
SHORTENER_API2 = environ.get("SHORTENER_API2", "")
SHORTENER_WEBSITE2 = environ.get("SHORTENER_WEBSITE2", "")
SHORTENER_API3 = environ.get("SHORTENER_API3", "")
SHORTENER_WEBSITE3 = environ.get("SHORTENER_WEBSITE3", "")

TWO_VERIFY_GAP = int(environ.get('TWO_VERIFY_GAP', "1200"))
THREE_VERIFY_GAP = int(environ.get('THREE_VERIFY_GAP', "54000"))

# ============================
# Channel & Group Links
# ============================
GRP_LNK = environ.get('GRP_LNK', 'https://t.me/DownTownVilla')
OWNER_LNK = environ.get('OWNER_LNK', 'https://t.me/DownTownVillaOwner')
UPDATE_CHNL_LNK = environ.get('UPDATE_CHNL_LNK', 'https://t.me/DownTownVilla')

# ============================
# User Configuration
# ============================
auth_users = [int(user) if id_pattern.search(user) else user for user in environ.get('AUTH_USERS', '').split()]
AUTH_USERS = (auth_users + ADMINS) if auth_users else []
PREMIUM_USER = [int(user) if id_pattern.search(user) else user for user in environ.get('PREMIUM_USER', '').split()]

# ============================
# Miscellaneous
# ============================
ULTRA_FAST_MODE = is_enabled(environ.get('ULTRA_FAST_MODE', "False"), True)
MAX_B_TN = environ.get("MAX_B_TN", "5")
PORT = int(environ.get("PORT", "8080"))
MSG_ALRT = environ.get('MSG_ALRT', 'Share & Support Us ♥️')
DELETE_TIME = int(environ.get("DELETE_TIME", "300"))
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", f"{script.CAPTION}")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", CUSTOM_FILE_CAPTION)
IMDB_TEMPLATE = environ.get("IMDB_TEMPLATE", f"{script.IMDB_TEMPLATE_TXT}")
MAX_LIST_ELM = int(environ.get("MAX_LIST_ELM") or 10) or None
INDEX_REQ_CHANNEL = int(environ.get('INDEX_REQ_CHANNEL', LOG_CHANNEL))
NO_RESULTS_MSG = is_enabled(environ.get("NO_RESULTS_MSG", "True"), True)
MAX_BTN = is_enabled((environ.get('MAX_BTN', "True")), True)
P_TTI_SHOW_OFF = is_enabled((environ.get('P_TTI_SHOW_OFF', "False")), False)
IMDB = is_enabled((environ.get('IMDB', "True")), False)
TMDB_ON_SEARCH = is_enabled((environ.get('TMDB_ON_SEARCH', "False")), False)
AUTO_FFILTER = is_enabled((environ.get('AUTO_FFILTER', "True")), True)
AUTO_DELETE = is_enabled((environ.get('AUTO_DELETE', "True")), True)
LONG_IMDB_DESCRIPTION = is_enabled(environ.get("LONG_IMDB_DESCRIPTION", "False"), False)
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
MELCOW_NEW_USERS = is_enabled((environ.get('MELCOW_NEW_USERS', "False")), False)
PROTECT_CONTENT = is_enabled((environ.get('PROTECT_CONTENT', "False")), False)
PM_SEARCH = is_enabled(environ.get('PM_SEARCH', "True"), True)
EMOJI_MODE = is_enabled(environ.get('EMOJI_MODE', "True"), True)
BUTTON_MODE = is_enabled((environ.get('BUTTON_MODE', "False")), False)
STREAM_MODE = is_enabled(environ.get('STREAM_MODE', "True"), True)
PREMIUM_STREAM_MODE = is_enabled(environ.get('PREMIUM_STREAM_MODE', "False"), False)
MAINTENANCE = is_enabled(environ.get('MAINTENANCE', "False"), False)

# ============================
# Bot Configuration
# ============================
AUTH_REQ_CHANNELS = [int(ch) for ch in auth_req_channels.split() if ch and id_pattern.match(ch)]
AUTH_CHANNELS = [int(ch) for ch in auth_channels.split() if ch and id_pattern.match(ch)]
REQST_CHANNEL = int(reqst_channel) if reqst_channel and id_pattern.search(reqst_channel) else None
SUPPORT_CHAT_ID = int(support_chat_id) if support_chat_id and id_pattern.search(support_chat_id) else None

LANGUAGES = {
    "ᴍᴀʟᴀʏᴀʟᴀᴍ":"mal", "ᴛᴀᴍɪʟ":"tam", "ᴇɴɢʟɪsʜ":"eng", "ʜɪɴᴅɪ":"hin",
    "ᴛᴇʟᴜɢᴜ":"tel", "ᴋᴀɴɴᴀᴅᴀ":"kan", "ɢᴜᴊᴀʀᴀᴛɪ":"guj", "ᴍᴀʀᴀᴛʜɪ":"mar",
    "ᴘᴜɴᴊᴀʙɪ":"pun"
}
QUALITIES = ["360P", "480P", "720P", "1080P", "1440P", "2160P", "4K"]
SEASON_COUNT = 12
SEASONS = [f"S{str(i).zfill(2)}" for i in range(1, SEASON_COUNT + 1)]
BAD_WORDS = {
    "PrivateMovieZ", "toonworld4all", "themoviesboss", "1tamilmv",
    "tamilblasters", "1tamilblasters", "skymovieshd", "extraflix",
    "hdm2", "moviesmod", "hdhub4u", "mkvcinemas", "primefix", "join",
    "www", "villa", "tg", "original"
}

# ============================
# Server & Web
# ============================
ON_HEROKU = 'DYNO' in environ
APP_NAME = environ.get('APP_NAME', None) if ON_HEROKU else None
BIND_ADDRESS = getenv('WEB_SERVER_BIND_ADDRESS', '0.0.0.0')
FQDN = (
    environ.get('FQDN', BIND_ADDRESS)
    if not ON_HEROKU or environ.get('FQDN')
    else f"{APP_NAME}.herokuapp.com"
)
FQDN = re.sub(r'^https?://', '', str(FQDN)).rstrip('/')
NO_PORT = is_enabled(environ.get('NO_PORT'), False)
HAS_SSL = is_enabled(getenv('HAS_SSL'), True)

if HAS_SSL:
    URL = f"https://{FQDN}/"
else:
    URL = f"http://{FQDN}/" if NO_PORT else f"http://{FQDN}:{PORT}/"

SLEEP_THRESHOLD = int(environ.get('SLEEP_THRESHOLD', '60'))
WORKERS = int(environ.get('WORKERS', '4'))
SESSION_NAME = str(environ.get('SESSION_NAME', 'downTownVillaBot'))
MULTI_CLIENT = False
name = str(environ.get('name', 'DOWNTOWNVILLA'))
PING_INTERVAL = int(environ.get("PING_INTERVAL", "298"))

# ============================
# Reactions
# ============================
REACTIONS = ["🤝", "😇", "🤗", "😍", "👍", "🎅", "😐", "🥰", "🤩", "😱", "🤣", "😘", "👏", "😛", "😈", "🎉", "⚡️", "🫡", "🤓", "😎", "🏆", "🔥", "🤭", "🌚", "🆒", "👻", "😁"]

# ============================
# Commands
# ============================
Bot_cmds = {
    "start": "Sᴛᴀʀᴛ Mᴇ Bᴀʙʏ",
    "stats": "Gᴇᴛ Bᴏᴛ Sᴛᴀᴛs",
    "alive": "Cʜᴇᴄᴋ Bᴏᴛ Aʟɪᴠᴇ ᴏʀ Nᴏᴛ",
    "settings": "ᴄʜᴀɴɢᴇ sᴇᴛᴛɪɴɢs",
    "id": "ɢᴇᴛ ɪᴅ ᴛᴇʟᴇɢʀᴀᴍ",
    "info": "Gᴇᴛ Usᴇʀ ɪɴғᴏ",
    "del_msg": "ʀᴇᴍᴏᴠᴇ ғɪʟᴇ ɴᴀᴍᴇ ᴄᴏʟʟᴇᴄᴛɪᴏɴ ɴᴏтɪғɪᴄᴀᴛɪᴏɴ...",
    "movie_update": "ᴏɴ ᴏғғ ᴀᴄᴄᴏʀᴅɪɴɢ ʏᴏᴜʀ ɴᴇᴇᴅᴇᴅ...",
    "pm_search": "ᴘᴍ sᴇᴀʀᴄʜ ᴏɴ ᴏғғ ᴀᴄᴄᴏʀᴅɪɴɢ ʏᴏᴜʀ ɴᴇᴇᴅᴇᴅ...",
    "trendlist": "Gᴇᴛ Tᴏᴘ Tʀᴀɴᴅɪɴɢ Sᴇᴀʀᴄʜ Lɪsᴛ",
    "broadcast": "ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴀ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ᴀʟʟ ᴜꜱᴇʀꜱ.",
    "grp_broadcast": "ʙʀᴏᴀᴅᴄᴀsᴛ ᴀ ᴍᴇssᴀɢᴇ ᴛᴏ ᴀʟʟ ᴄᴏɴɴᴇᴄᴛᴇᴅ ɢʀᴏᴜᴘs",
    "send": "ꜱᴇɴᴅ ᴍᴇꜱꜱᴀɢᴇ ᴛᴏ ᴀ ᴘᴀʀᴛɪᴄᴜʟᴀʀ ᴜꜱᴇʀ.",
    "add_premium": "ᴀᴅᴅ ᴀɴʏ ᴜꜱᴇʀ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ.",
    "remove_premium": "ʀᴇᴍᴏᴠᴇ ᴀɴʏ ᴜꜱᴇʀ ꜰʀᴏᴍ ᴘʀᴇᴍɪᴜᴍ.",
    "premium_users": "ɢᴇᴛ ʟɪꜱᴛ ᴏꜰ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ.",
    "restart": "ʀᴇꜱᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ.",
    "group_cmd": "ɢʀᴏᴜᴘ ᴄᴏᴍᴍᴀɴᴅ ʟɪꜱᴛ",
    "admin_cmd": "ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs ʟɪsᴛ.",
    "reset_group": "Group Setting Default",
    "trial_reset": "User Trial Reset",
    "remove_fsub": "Remove Forced Subscription (group admin only)",
    "maintenance": "Maintenance Mode (Admin Only)",
}

# ============================
# Logs Configuration
# ============================
LOG_STR = "Current Customized Configurations are:-\n"
LOG_STR += ("IMDB Results are enabled, Bot will be showing imdb details for your queries.\n" if IMDB else "IMDB Results are disabled.\n")
LOG_STR += ("P_TTI_SHOW_OFF found, Users will be redirected to send /start to Bot PM instead of sending file directly.\n" if P_TTI_SHOW_OFF else "P_TTI_SHOW_OFF is disabled, files will be sent in PM instead of starting the bot.\n")
LOG_STR += ("BUTTON_MODE is found, filename and file size will be shown in a single button instead of two separate buttons.\n" if BUTTON_MODE else "BUTTON_MODE is disabled, filename and file size will be shown as different buttons.\n")
LOG_STR += (f"CUSTOM_FILE_CAPTION enabled with value {CUSTOM_FILE_CAPTION}, your files will be sent along with this customized caption.\n" if CUSTOM_FILE_CAPTION else "No CUSTOM_FILE_CAPTION Found, Default captions of file will be used.\n")
LOG_STR += ("Long IMDB storyline enabled." if LONG_IMDB_DESCRIPTION else "LONG_IMDB_DESCRIPTION is disabled, Plot will be shorter.\n")
LOG_STR += ("Spell Check Mode is enabled, bot will be suggesting related movies if movie name is misspelled.\n" if SPELL_CHECK_REPLY else "Spell Check Mode is disabled.\n")

# Ensure legacy compatibility
DATABASE_URI2 = _DB_URIS[1] if len(_DB_URIS) > 1 else DATABASE_URI
DATABASE_URI3 = _DB_URIS[2] if len(_DB_URIS) > 2 else DATABASE_URI2
