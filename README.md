Here is the **complete README.md** file with **DOWNTOWN VILLA** branding. Copy and paste the entire content below into your `README.md` file.

---

```markdown
<h1 align="center">DOWNTOWN VILLA BOT</h1>

<p align="center">
  <b>Powerful Telegram auto-filter, file indexing, verification, premium, and streaming bot.</b>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/DreamXBotz/Pics/main/dreamxbotz.jpg" alt="DOWNTOWN VILLA Logo" width="220">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Ready">
  <img src="https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Telegram Bot">
</p>

<p align="center">
  <a href="https://t.me/DownTownVillaBot">
    <img src="https://img.shields.io/badge/Demo%20Bot-Click%20Here-blue?style=for-the-badge&logo=telegram" alt="Demo Bot">
  </a>
  <a href="https://t.me/DownTownVillaSupport">
    <img src="https://img.shields.io/badge/Support%20Group-Join-blue?style=for-the-badge&logo=telegram" alt="Support Group">
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Auto%20Filter-Fast%20Search-ff69b4?style=flat-square" alt="Auto Filter">
  <img src="https://img.shields.io/badge/MongoDB-Database-47A248?style=flat-square&logo=mongodb&logoColor=white" alt="MongoDB">
  <img src="https://img.shields.io/badge/Streaming-Supported-orange?style=flat-square" alt="Streaming">
  <img src="https://img.shields.io/badge/Premium-Enabled-purple?style=flat-square" alt="Premium">
  <img src="https://img.shields.io/badge/Verification-3%20Step-red?style=flat-square" alt="Verification">
</p>

**DOWNTOWN VILLA BOT** is a Telegram auto-filter bot for indexing files from channels/groups, searching them quickly, and sharing files through bot commands. It supports MongoDB storage, group settings, force subscription, verification, premium users, streaming links, and admin tools.

> This project is intended for educational use. Use it responsibly and follow Telegram rules, hosting provider rules, and copyright laws.

## Table Of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Environment Variables](#environment-variables)
- [Deploy On Render](#deploy-on-render)
- [Deploy On Heroku](#deploy-on-heroku)
- [Deploy With Docker](#deploy-with-docker)
- [Local Setup](#local-setup)
- [Commands](#commands)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)

## Features

| Search & Indexing | Access Control | Admin Tools |
| --- | --- | --- |
| Fast auto-filter search | Force subscription | Broadcast tools |
| Auto file indexing | Request-to-join FSub | User ban/unban |
| Caption-based filtering | Three-step verification | Chat enable/disable |
| Trending search list | Premium user support | Maintenance mode |
| Movie/series search | PM search toggle | Logs and stats |

| Media & Streaming | Database | Customization |
| --- | --- | --- |
| Online streaming links | MongoDB support | Group settings menu |
| Fast download links | Multiple DB support | Custom captions |
| Telegraph media info | User/chat database | IMDb templates |
| TMDB movie metadata | Referral and premium data | Shortener settings |
| Auto-delete tools | Search analytics | Tutorial links |

## Requirements

- Python 3.12+
- MongoDB database URI
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Telegram `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org)
- A log channel where the bot is added as admin

## Environment Variables

### Required

| Variable | Required | Description | Usage |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Yes | Telegram bot token from BotFather | Used to authenticate the bot. |
| `API_ID` | Yes | Telegram API ID from my.telegram.org | Required for Pyrogram client. |
| `API_HASH` | Yes | Telegram API hash from my.telegram.org | Required for Pyrogram client. |
| `DATABASE_URI` | Yes | Primary MongoDB connection URI | Stores indexed files, users, groups, etc. |
| `LOG_CHANNEL` | Yes | Telegram log channel ID (e.g., `-100...`) | Sends startup logs, errors, and user/group notifications. |
| `ADMINS` | Yes | Space‑separated Telegram user IDs or usernames | Grants admin access to bot commands. |

### Recommended

| Variable | Recommended | Description | Usage |
| --- | --- | --- | --- |
| `CHANNELS` | Recommended | Space‑separated channel/group IDs for indexing | Bot indexes files from these chats. |
| `DATABASE_NAME` | Recommended | MongoDB database name (default: `Cluster0`) | Specifies the database to use. |
| `COLLECTION_NAME` | Recommended | MongoDB collection name (default: `downtown_villa_files`) | Stores the indexed file records. |

### Optional

| Variable | Default | Description | Usage |
| --- | --- | --- | --- |
| `DATABASE_URI_1` | Empty | Additional MongoDB URI (for multi‑DB support) | Adds a second database to the pool. |
| `DATABASE_URI_2` | Empty | Additional MongoDB URI | Adds a third database to the pool. |
| `DATABASE_URI_3` | Empty | Additional MongoDB URI | Adds a fourth database to the pool. |
| `BIN_CHANNEL` | `-100` | Channel used for file/bin logs | Stores temporary media for streaming. |
| `PREMIUM_LOGS` | `-100` | Premium activity log channel | Sends premium purchase and expiry logs. |
| `AUTH_CHANNELS` | `-100` | Force subscription channel IDs | Users must join these channels to use the bot. |
| `AUTH_REQ_CHANNELS` | `-100` | Request‑to‑join force subscription channel IDs | Users request to join; bot approves manually. |
| `REQST_CHANNEL_ID` | `-100` | Request channel ID | Stores user file requests. |
| `SUPPORT_CHAT_ID` | `-100` | Support group ID | For feedback and support requests. |
| `SUPPORT_CHAT` | `https://t.me/` | Support group link | Displayed to users when needed. |
| `FQDN` | Web bind address | Public domain for stream links | Used to generate stream/download URLs. |
| `PORT` | `8080` | Web server port | Port on which the streaming server runs. |
| `HAS_SSL` | `True` | Use HTTPS in generated stream URLs | Ensures secure links. |
| `NO_PORT` | `False` | Hide port in generated HTTP stream URLs | Removes `:port` from URLs when behind a proxy. |
| `STREAM_MODE` | `True` | Enable stream mode | Adds stream/download buttons to file results. |
| `PREMIUM_STREAM_MODE` | `False` | Restrict stream mode to premium users | If `True`, only premium users get stream links. |
| `MAINTENANCE` | `False` | Enable maintenance mode | Disables all bot commands for non‑admins. |
| `IS_VERIFY` | `False` | Enable verification system | Requires users to verify via shorteners. |
| `SHORTENER_API` | Empty | Shortener API key for verification links | Used for the first verification link. |
| `SHORTENER_WEBSITE` | Empty | Shortener domain | Domain for the first shortener. |
| `SHORTENER_API2` | Empty | Shortener API key for second verification | Used for the second verification link. |
| `SHORTENER_WEBSITE2` | Empty | Shortener domain for second shortener | Domain for the second shortener. |
| `SHORTENER_API3` | Empty | Shortener API key for third verification | Used for the third verification link. |
| `SHORTENER_WEBSITE3` | Empty | Shortener domain for third shortener | Domain for the third shortener. |
| `TMDB_API_KEY` | Empty | TMDB API key for movie metadata | Enables TMDB poster/data in search results and movie notifications. |
| `TMDB_BEARER_TOKEN` | Empty | Optional TMDB bearer token | Alternative to API key. |
| `TELEGRAPH_ACCESS_TOKEN` | Empty | Optional Telegraph access token | Used for uploading media info pages. |
| `MOVIE_UPDATE_NOTIFICATION` | `False` | Toggle movie update notifications | Sends updates to `MOVIE_UPDATE_CHANNEL` when new files are indexed. |
| `MOVIE_UPDATE_CHANNEL` | `-100` | Channel for movie update notifications | If `MOVIE_UPDATE_NOTIFICATION` is `True`, posts go here. |
| `DREAMXBOTZ_IMAGE_FETCH` | `True` | Enable image fetching for TMDB posters | Fetches and resizes images for better display. (Legacy name kept for compatibility) |
| `LINK_PREVIEW` | `False` | Shows link preview in notification msg instead of image | If `True`, sends a text link instead of an image. |
| `ABOVE_PREVIEW` | `True` | Shows link preview above the text in notification msg | If `True`, places link above text. |
| `LANDSCAPE_POSTER` | `True` | Shows landscape poster in notification msg | Uses backdrop instead of portrait. |
| `LONG_IMDB_DESCRIPTION` | `False` | Long IMDB description | Enables full plot in search results. |
| `SPELL_CHECK_REPLY` | `True` | Spell check mode | Suggests correct movie names on misspelling. |
| `MELCOW_NEW_USERS` | `False` | Welcome new users in groups | Sends a welcome message when new members join. |
| `PROTECT_CONTENT` | `False` | Protect content | Prevents forwarding of files sent by the bot. |
| `PM_SEARCH` | `True` | PM search on/off | Allows search in private chat. |
| `EMOJI_MODE` | `True` | Emoji status | Adds emoji reactions to messages. |
| `BUTTON_MODE` | `False` | Button mode | If `True`, file results shown as buttons; otherwise as text links. |
| `MAX_B_TN` | `5` | Maximum buttons per row | Controls number of file buttons per row. |
| `AUTO_FFILTER` | `True` | Auto filter on/off | Automatically filters files when a query is sent. |
| `AUTO_DELETE` | `True` | Auto delete on/off | Automatically deletes search messages after a certain time. |
| `DELETE_TIME` | `300` | Auto‑delete time (seconds) | Time before auto‑deleting search results. |
| `CUSTOM_FILE_CAPTION` | Empty | Custom caption for files | Overrides default captions with your own text. |
| `IMDB_TEMPLATE` | Default template | Custom IMDB result template | Customize how movie details appear. |
| `MAX_LIST_ELM` | `10` | Max elements in list | Limits list of titles in search results. |
| `INDEX_REQ_CHANNEL` | `LOG_CHANNEL` | Index request channel | Channel for indexing requests. |
| `NO_RESULTS_MSG` | `True` | Send "no results" message to log channel | If `True`, logs failed searches. |
| `GRP_LNK` | `https://t.me/` | Group link | Link to your main movie group. |
| `OWNER_LNK` | `https://t.me/` | Owner link | Link to bot owner. |
| `UPDATE_CHNL_LNK` | `https://t.me/` | Update channel link | Link to your update channel. |
| `QR_CODE` | Empty | Payment QR code image URL | Displayed in premium purchase menu. |
| `OWNER_UPI_ID` | Empty | UPI ID for payments | For UPI payments. |
| `PREMIUM_LOGS` | `-100` | Premium logs channel | Logs premium transactions. |
| `REACTIONS` | List of emojis | Reactions used in EMOJI_MODE | Default reactions set. |

**Note:** Some variable names still contain "DREAMXBOTZ" (e.g., `DREAMXBOTZ_IMAGE_FETCH`) due to backward compatibility with the original code. They function as described.

## Example `.env`

Copy `.env.example` to `.env` and fill your real values:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=123456:your_bot_token
API_ID=123456
API_HASH=your_api_hash
DATABASE_URI=mongodb+srv://username:db-password@cluster.mongodb.net/
DATABASE_NAME=Cluster0
COLLECTION_NAME=downtown_villa_files
ADMINS=123456789
CHANNELS=-1001234567890
LOG_CHANNEL=-1001234567890
BIN_CHANNEL=-1001234567890
FQDN=your-app-name.onrender.com
HAS_SSL=True
NO_PORT=True
```

## Deploy On Render

1. Fork or upload this repository to GitHub.
2. Create a new Render Web Service.
3. Select Docker as the runtime.
4. Add the required environment variables from the table above.
5. Deploy the service.

Render must receive a valid `PORT` environment variable or use the default `8080`. If stream links use your Render domain, set:

```env
FQDN=your-app-name.onrender.com
HAS_SSL=True
NO_PORT=True
```

## Deploy On Heroku

This repository includes `app.json`, `Procfile`, and `heroku.yml`, so it can also run on Heroku-style deployments.

1. Create a Heroku app.
2. Add the required environment variables.
3. Deploy this repository.
4. Ensure the worker or web process is enabled according to your hosting setup.

## Deploy With Docker

Build the image:

```bash
docker build -t downtownvilla .
```

Run the container:

```bash
docker run --env-file .env -p 8080:8080 downtownvilla
```

For Docker Compose, `.env` is optional at compose-load time, but the bot still needs required variables from `.env` or your shell environment.

## Local Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file from the example and add your configuration:

```bash
cp .env.example .env
```

Then run:

```bash
python bot.py
```

## Commands

### User Commands

| Command | Description |
| --- | --- |
| `/start` | Start the bot |
| `/settings` | Open group settings |
| `/id` | Get Telegram ID |
| `/info` | Get user information |
| `/imdb` | Search IMDb/movie details |
| `/search` | Search IMDb/movie details |
| `/movies` | Search movie titles in private chat |
| `/series` | Search series titles in private chat |
| `/plan` | View premium plans |
| `/myplan` | Check active premium plan |
| `/redeem` | Redeem a premium code |
| `/font` | Generate styled text in private chat |
| `/img` | Upload replied media to Telegraph |
| `/cup` | Upload replied media to Telegraph |
| `/telegraph` | Upload replied media to Telegraph |
| `/stickerid` | Get sticker file ID |
| `/alive` | Check bot status |
| `/ping` | Check bot response time |
| `/system` | Show system information |
| `/request` | Send a group request report |
| `#request` | Send a group request report |

### Admin Commands

| Command | Description |
| --- | --- |
| `/stats` | Show database stats |
| `/logs` | Get bot logs |
| `/commands` | Set bot command menu |
| `/movie_update` | Toggle movie update notifications |
| `/pm_search` | Toggle private message search |
| `/verify` | Manage verification status |
| `/delete` | Delete a specific file from database |
| `/deleteall` | Delete all files from database |
| `/deletefiles` | Delete PreDVD/CamRip files |
| `/save` | Save replied file to the bot |
| `/send` | Send a message to a user |
| `/post` | Create a formatted post from a replied file |
| `/setskip` | Set skip count for indexing forwarded links |
| `/broadcast` | Broadcast to users |
| `/grp_broadcast` | Broadcast to groups |
| `/clear_junk` | Clean junk users |
| `/junk_group` | Clean junk groups |
| `/clear_junk_group` | Clean junk groups |
| `/clean_groups` | Clean invalid or inactive groups |
| `/ban` | Ban a user |
| `/unban` | Unban a user |
| `/banned` | List banned users |
| `/users` | List saved users |
| `/chats` | List saved chats |
| `/invite` | Create invite link for a chat |
| `/enable` | Enable a disabled group |
| `/disable` | Disable a group |
| `/leave` | Make bot leave a group |
| `/add_premium` | Add premium access |
| `/get_premium` | Generate premium payment link |
| `/remove_premium` | Remove premium access |
| `/premium_users` | List premium users |
| `/add_redeem` | Create redeem code |
| `/restart` | Restart the bot |
| `/reload` | Reload group settings |
| `/del_msg` | Delete bot messages |
| `/maintenance` | Toggle maintenance mode |
| `/group_cmd` | Show group command list |
| `/admin_cmd` | Show admin command list |
| `/top_search` | Show top searched items |
| `/trendlist` | Show trending searches |
| `/set_template` | Set IMDb template |
| `/set_caption` | Set custom file caption |
| `/set_tutorial` | Set first verification tutorial link |
| `/set_tutorial_2` | Set second verification tutorial link |
| `/set_tutorial_3` | Set third verification tutorial link |
| `/set_shortner` | Set first shortener |
| `/set_shortner_2` | Set second shortener |
| `/set_shortner_3` | Set third shortener |
| `/set_log_channel` | Set group log channel |
| `/set_time` | Set second verification gap |
| `/set_time_2` | Set third verification gap |
| `/details` | Show group verification settings |
| `/set_fsub` | Set force subscription channels |
| `/resetallgroup` | Reset all group settings |
| `/trial_reset` | Reset user trial |
| `/remove_fsub` | Remove force subscription from a group |
| `/delreq` | Delete saved join requests |

Indexing is handled by forwarding channel messages or sending supported Telegram message links to the bot in private chat.

## Public Repo Safety

- Do not commit `.env`, session files, logs, or virtual environments.
- Rotate any token or API key that was previously committed publicly.
- Keep real values only in your hosting provider environment variables.
- For public forks, avoid hardcoding shortener, TMDB, Telegraph, MongoDB, or Telegram credentials.

## Troubleshooting

### Bot does not start

Check that `BOT_TOKEN`, `API_ID`, `API_HASH`, `DATABASE_URI`, `LOG_CHANNEL`, and `ADMINS` are set correctly.

### MongoDB connection error

Check that `DATABASE_URI` is valid, the database user has access, and your hosting provider IP is allowed in MongoDB Atlas.

### Stream links are wrong

Set `FQDN`, `HAS_SSL`, and `NO_PORT` according to your hosting provider domain.

## License

This project is licensed under the [MIT License](LICENSE).

## Credits

Special thanks to:


Thanks to the original DreamxBotz community and all contributors who worked on the base project. DOWNTOWN VILLA is a rebranded fork with enhanced features.
```

---

You can now copy this entire block and paste it into `README.md`. No additional changes are needed.
