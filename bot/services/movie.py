"""
Movie metadata service for the new bot.

Responsibilities
----------------
- TMDB search and metadata retrieval
- IMDb-compatible metadata shape
- IMDb fallback through the existing IMDBKit dependency
- poster/backdrop URL selection
- optional image downloading/resizing
- title/year matching and normalization

The service is deliberately independent of Telegram handlers and database
repositories.  Callers can use ``get_movie_details()`` as the main entry point.
"""

from __future__ import annotations

import asyncio
import logging
import re
import warnings
from datetime import datetime
from difflib import SequenceMatcher
from io import BytesIO
from typing import Any, Optional

import aiohttp
from PIL import Image

from info import (
    DREAMXBOTZ_IMAGE_FETCH,
    MAX_LIST_ELM,
    TMDB_API_KEY,
)

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"
TMDB_IMAGE_W1280_URL = "https://image.tmdb.org/t/p/w1280"

MIN_RUNTIME = 40
REQUEST_TIMEOUT = 15

_session: Optional[aiohttp.ClientSession] = None


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

async def get_session() -> aiohttp.ClientSession:
    """Return the shared HTTP session."""
    global _session

    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        )

    return _session


async def close_session() -> None:
    """Close the shared HTTP session."""
    global _session

    if _session and not _session.closed:
        await _session.close()

    _session = None


# ---------------------------------------------------------------------------
# Generic formatting
# ---------------------------------------------------------------------------

def _list_to_str(
    values: Any,
    limit: int = 10,
    key: Optional[str] = None,
) -> Optional[str]:
    """Convert TMDB arrays into comma-separated strings."""
    if not values or not isinstance(values, list):
        return None

    items = values[:limit]

    if key:
        output = [
            str(item.get(key, "")).strip()
            for item in items
            if isinstance(item, dict) and item.get(key)
        ]
    else:
        output = [str(item).strip() for item in items if item]

    output = [item for item in output if item]
    return ", ".join(output) if output else None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _year_from_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    match = re.match(r"^(\d{4})", str(value))
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Query parsing / matching
# ---------------------------------------------------------------------------

def extract_title_and_year(query: str) -> tuple[str, Optional[int]]:
    """Extract a trailing four-digit year from a title."""
    query = str(query or "").strip()

    match = re.match(r"^(.*?)(?:\s+(\d{4}))?$", query)

    if not match:
        return query, None

    title, year = match.groups()

    return (
        title.strip(),
        int(year) if year and year.isdigit() else None,
    )


def normalize_title(value: str) -> str:
    """Normalize a title for fuzzy comparison."""
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def title_similarity(first: str, second: str) -> float:
    """Return a normalized fuzzy title similarity score."""
    first = normalize_title(first)
    second = normalize_title(second)

    if not first or not second:
        return 0.0

    return SequenceMatcher(None, first, second).ratio()


# ---------------------------------------------------------------------------
# TMDB HTTP
# ---------------------------------------------------------------------------

async def tmdb_get(
    path: str,
    params: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Perform an authenticated asynchronous TMDB GET request.

    TMDB v3 accepts either an API key or bearer token.  The new bot uses the
    configured TMDB_API_KEY when supplied.
    """
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    request_params = dict(params or {})
    headers: dict[str, str] = {}

    if api_key:
        request_params["api_key"] = api_key

    session = await get_session()

    async with session.get(
        url,
        params=request_params,
        headers=headers,
    ) as response:
        response.raise_for_status()
        return await response.json()


async def fetch_media_details(
    media_type: str,
    media_id: int,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch detailed TMDB data for a movie or TV show."""
    params = {
        "append_to_response": (
            "credits,external_ids,alternative_titles,"
            "release_dates,images"
        )
    }

    return await tmdb_get(
        f"{media_type}/{media_id}",
        params=params,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# TMDB search
# ---------------------------------------------------------------------------

async def search_media_id(
    query: str,
    api_key: Optional[str] = None,
) -> tuple[Optional[str], Optional[int]]:
    """
    Find the strongest TMDB movie/TV match.

    The matching strategy preserves the old bot's behavior:
    - extract year
    - try the complete title
    - try reduced queries if needed
    - fuzzy-score candidates
    - reject trailers/videos and very short movies
    - prefer already-released titles
    """
    title, requested_year = extract_title_and_year(query)

    if not title:
        return None, None

    words = title.split()

    queries = [title]

    if len(words) > 2:
        queries.extend([
            " ".join(words[:-1]),
            words[0],
        ])
    elif len(words) == 2:
        queries.append(words[0])

    queries = list(dict.fromkeys(queries))[:3]

    results: list[dict[str, Any]] = []

    for target_query in queries:
        if not target_query:
            continue

        response = await tmdb_get(
            "search/multi",
            params={
                "query": target_query,
                "language": "en-US",
                "page": 1,
                "include_adult": "false",
            },
            api_key=api_key,
        )

        results = response.get("results", [])

        if results:
            break

    if not results:
        return None, None

    scored = []

    for result in results:
        media_type = result.get("media_type")

        if media_type not in {"movie", "tv"}:
            continue

        candidate_title = result.get("title") or result.get("name")
        ratio = title_similarity(candidate_title, title)

        if ratio >= 0.5:
            scored.append((result, ratio))

    if not scored:
        scored = [
            (
                result,
                title_similarity(
                    result.get("title") or result.get("name"),
                    title,
                ),
            )
            for result in results[:10]
            if result.get("media_type") in {"movie", "tv"}
        ]

    today = datetime.utcnow().date()

    past: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []

    for result, ratio in scored:
        media_type = result.get("media_type")

        release_string = (
            result.get("release_date")
            or result.get("first_air_date")
        )

        if not release_string:
            continue

        try:
            release_date = datetime.strptime(
                release_string,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            continue

        if requested_year:
            if abs(release_date.year - requested_year) > 1:
                continue

        # Movies shorter than MIN_RUNTIME and videos/trailers are ignored.
        if media_type == "movie":
            try:
                details = await fetch_media_details(
                    media_type,
                    result["id"],
                    api_key=api_key,
                )

                runtime = details.get("runtime")
                is_video = details.get("video", False)

                if is_video or (
                    runtime is not None
                    and runtime < MIN_RUNTIME
                ):
                    continue
            except Exception:
                continue

        candidate = {
            "type": media_type,
            "id": result["id"],
            "date": release_date,
            "ratio": ratio,
            "popularity": result.get("popularity", 0),
        }

        if release_date > today:
            upcoming.append(candidate)
        else:
            past.append(candidate)

    # Strong title match first, then release date/popularity.
    past.sort(
        key=lambda item: (
            item["ratio"],
            item["date"],
            item["popularity"],
        ),
        reverse=True,
    )

    upcoming.sort(
        key=lambda item: (
            item["ratio"],
            item["date"],
            item["popularity"],
        ),
        reverse=True,
    )

    candidates = past or upcoming

    if not candidates:
        return None, None

    selected = candidates[0]

    return selected["type"], selected["id"]


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def process_images(images_data: dict[str, Any]) -> dict[str, Any]:
    """Organize TMDB posters and backdrops by language."""
    posters_by_language: dict[str, list[str]] = {}
    backdrops_by_language: dict[str, list[str]] = {}

    for image in images_data.get("posters", []):
        file_path = image.get("file_path")
        if not file_path:
            continue

        language = image.get("iso_639_1") or "no_lang"

        posters_by_language.setdefault(language, []).append(
            f"{TMDB_IMAGE_BASE_URL}{file_path}"
        )

    for image in images_data.get("backdrops", []):
        file_path = image.get("file_path")
        if not file_path:
            continue

        language = image.get("iso_639_1") or "no_lang"

        backdrops_by_language.setdefault(language, []).append(
            f"{TMDB_IMAGE_BASE_URL}{file_path}"
        )

    posters_by_language["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{image['file_path']}"
        for image in images_data.get("posters", [])
        if image.get("file_path")
    ]

    backdrops_by_language["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{image['file_path']}"
        for image in images_data.get("backdrops", [])
        if image.get("file_path")
    ]

    languages = sorted(
        set(posters_by_language) |
        set(backdrops_by_language)
    )

    return {
        "posters": posters_by_language,
        "backdrops": backdrops_by_language,
        "available_languages": languages,
    }


def select_poster(
    images: dict[str, Any],
    original_language: Optional[str],
    fallback: Optional[str] = None,
) -> Optional[str]:
    """Select the preferred poster language."""
    posters = images.get("posters", {})

    if fallback:
        return fallback

    for language in ("en", original_language, "xx", "no_lang"):
        if language and posters.get(language):
            return posters[language][0]

    if posters.get("all"):
        return posters["all"][0]

    return None


def select_backdrop(
    images: dict[str, Any],
    original_language: Optional[str],
) -> Optional[str]:
    """Select the preferred backdrop language."""
    backdrops = images.get("backdrops", {})

    for language in ("en", original_language, "xx", "no_lang"):
        if language and backdrops.get(language):
            return backdrops[language][0]

    if backdrops.get("all"):
        return backdrops["all"][0]

    return None


async def fetch_image(
    url: Optional[str],
    size: tuple[int, int] = (860, 1200),
):
    """
    Download and resize an image.

    If image fetching is disabled, the original URL is returned so callers
    can still send the remote image directly.
    """
    if not url:
        return None

    if not DREAMXBOTZ_IMAGE_FETCH:
        return url

    try:
        session = await get_session()

        async with session.get(url) as response:
            if response.status != 200:
                logger.error(
                    "Image request returned %s: %s",
                    response.status,
                    url,
                )
                return None

            data = await response.read()

        image = Image.open(BytesIO(data)).convert("RGB")
        image = image.resize(size, Image.LANCZOS)

        output = BytesIO()
        image.save(output, format="JPEG", quality=90)
        output.seek(0)

        return output

    except aiohttp.ClientError as exc:
        logger.error("Image request failed: %s", exc)
    except (OSError, ValueError) as exc:
        logger.error("Image processing failed: %s", exc)
    except Exception:
        logger.exception("Unexpected image error")

    return None


# ---------------------------------------------------------------------------
# TMDB data assembly
# ---------------------------------------------------------------------------

async def fetch_tmdb_data(
    query: str,
    api_key: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Search TMDB and return a normalized movie/TV metadata dictionary."""
    media_type, media_id = await search_media_id(
        query,
        api_key=api_key,
    )

    if not media_id or not media_type:
        return None

    details = await fetch_media_details(
        media_type,
        media_id,
        api_key=api_key,
    )

    credits = details.get("credits", {})
    crew = credits.get("crew", [])

    # US certification.
    certificate = None

    if media_type == "movie":
        release_dates = details.get("release_dates", {})
        us_results = [
            item
            for item in release_dates.get("results", [])
            if item.get("iso_3166_1") == "US"
        ]

        if us_results:
            dates = us_results[0].get("release_dates", [])
            if dates:
                certificate = dates[0].get("certification") or None

    if media_type == "movie":
        runtime = details.get("runtime")
        runtime_display = f"{runtime} min" if runtime else None
    else:
        runtime_values = _list_to_str(
            details.get("episode_run_time", []),
            limit=10,
        )
        runtime_display = (
            f"{runtime_values} min"
            if runtime_values
            else None
        )

    images = process_images(details.get("images", {}))
    original_language = details.get("original_language")

    images["original_language"] = original_language

    poster = select_poster(
        images,
        original_language,
        fallback=(
            f"{TMDB_IMAGE_BASE_URL}{details['poster_path']}"
            if details.get("poster_path")
            else None
        ),
    )

    backdrop = select_backdrop(
        images,
        original_language,
    )

    if poster:
        poster = poster.replace(
            "/original/",
            "/w1280/",
        )

    if backdrop:
        backdrop = backdrop.replace(
            "/original/",
            "/w1280/",
        )

    release_date = (
        details.get("release_date")
        or details.get("first_air_date")
    )

    output = {
        "query": query,
        "media_type": media_type,
        "media_id": media_id,
        "title": details.get("title") or details.get("name"),
        "localized_title": (
            details.get("original_title")
            or details.get("original_name")
        ),
        "aka": _list_to_str(
            details.get("alternative_titles", {}).get("titles", []),
            key="title",
        ),
        "kind": media_type,
        "year": _year_from_date(release_date),
        "release_date": release_date,
        "imdb_id": details.get("external_ids", {}).get("imdb_id"),
        "tmdb_id": details.get("id"),
        "rating": details.get("vote_average"),
        "votes": details.get("vote_count"),
        "runtime": runtime_display,
        "certificates": certificate,
        "genres": _list_to_str(
            details.get("genres", []),
            key="name",
        ),
        "languages": _list_to_str(
            details.get("spoken_languages", []),
            key="english_name",
        ),
        "countries": _list_to_str(
            details.get("production_countries", []),
            key="name",
        ),
        "director": _list_to_str(
            [
                person
                for person in crew
                if person.get("job") == "Director"
            ],
            key="name",
        ),
        "writer": _list_to_str(
            [
                person
                for person in crew
                if person.get("job") in {
                    "Screenplay",
                    "Writer",
                    "Story",
                }
            ],
            key="name",
        ),
        "producer": _list_to_str(
            [
                person
                for person in crew
                if person.get("job") == "Producer"
            ],
            key="name",
        ),
        "composer": _list_to_str(
            [
                person
                for person in crew
                if person.get("job") == "Original Music Composer"
            ],
            key="name",
        ),
        "cinematographer": _list_to_str(
            [
                person
                for person in crew
                if person.get("job") == "Director of Photography"
            ],
            key="name",
        ),
        "cast": _list_to_str(
            credits.get("cast", []),
            limit=15,
            key="name",
        ),
        "plot": details.get("overview"),
        "tagline": details.get("tagline"),
        "box_office": (
            details.get("revenue")
            if details.get("revenue", 0) > 0
            else None
        ),
        "distributors": _list_to_str(
            details.get("production_companies", []),
            key="name",
        ),
        "poster_url": poster,
        "backdrop_url": backdrop,
        "url": (
            f"https://www.themoviedb.org/"
            f"{media_type}/{details.get('id')}"
        ),
        "images": images,
    }

    if media_type == "tv":
        output.update({
            "seasons": details.get("number_of_seasons"),
            "episodes": details.get("number_of_episodes"),
        })
    else:
        output["seasons"] = None
        output["episodes"] = None

    return output


# ---------------------------------------------------------------------------
# IMDb fallback
# ---------------------------------------------------------------------------

def _get_imdb_client():
    """Load the legacy IMDBKit client lazily."""
    try:
        from imdbkit import IMDBKit
        return IMDBKit()
    except Exception:
        logger.exception("IMDBKit could not be loaded")
        return None


def _imdb_list_to_str(
    values: Any,
    limit: Optional[int] = None,
) -> str:
    if not values:
        return "N/A"

    if isinstance(values, (str, int, float)):
        return str(values)

    result = []

    for item in values:
        if hasattr(item, "name"):
            item = item.name

        if item:
            result.append(str(item))

    if limit:
        result = result[:limit]

    return ", ".join(result) if result else "N/A"


async def get_imdb_details(
    query: str,
    *,
    bulk: bool = False,
    imdb_id: bool = False,
    file: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Fetch movie metadata through IMDBKit.

    This remains a fallback provider so the new bot still works when TMDB
    search/data retrieval fails.
    """
    imdb = _get_imdb_client()

    if imdb is None:
        return None

    search_query = str(query).strip().lower()

    try:
        if not imdb_id:
            title = search_query
            year_value = None

            years = re.findall(
                r"[1-2]\d{3}$",
                search_query,
            )

            if years:
                year_value = years[0]
                title = search_query.replace(
                    year_value,
                    "",
                ).strip()

            elif file:
                file_years = re.findall(
                    r"[1-2]\d{3}",
                    str(file),
                )
                if file_years:
                    year_value = file_years[0]

            result = await asyncio.to_thread(
                imdb.search_movie,
                title,
            )

            if not result or not result.titles:
                return None

            movies = result.titles[:MAX_LIST_ELM]

            if year_value:
                filtered = [
                    movie
                    for movie in movies
                    if movie.year
                    and str(movie.year) == str(year_value)
                ]

                if not filtered:
                    filtered = movies
            else:
                filtered = movies

            allowed_kinds = {
                "movie",
                "tv series",
                "tvSeries",
                "tvMiniSeries",
                "tvMovie",
            }

            filtered_kind = [
                movie
                for movie in filtered
                if movie.kind in allowed_kinds
            ]

            if not filtered_kind:
                filtered_kind = filtered

            if bulk:
                return filtered_kind[:MAX_LIST_ELM]

            if not filtered_kind:
                return None

            movie_id = filtered_kind[0].imdb_id
        else:
            movie_id = query

        movie = await asyncio.to_thread(
            imdb.get_movie,
            movie_id,
        )

        if not movie:
            return None

        release_date = (
            movie.release_date
            if movie.release_date
            else str(movie.year)
            if movie.year
            else "N/A"
        )

        plot = (
            movie.plot[0]
            if isinstance(movie.plot, list) and movie.plot
            else movie.plot or ""
        )

        plot = str(plot)
        if len(plot) > 800:
            plot = plot[:800] + "..."

        normalized_imdb_id = str(movie.imdb_id)

        if not normalized_imdb_id.startswith("tt"):
            normalized_imdb_id = f"tt{normalized_imdb_id}"

        info_series = getattr(movie, "info_series", None)
        display_seasons = getattr(
            info_series,
            "display_seasons",
            None,
        )

        return {
            "title": movie.title,
            "votes": movie.votes,
            "aka": _imdb_list_to_str(movie.title_akas),
            "seasons": (
                len(display_seasons)
                if display_seasons
                else None
            ),
            "box_office": movie.worldwide_gross,
            "localized_title": movie.title_localized,
            "kind": movie.kind,
            "imdb_id": normalized_imdb_id,
            "tmdb_id": None,
            "cast": _imdb_list_to_str(movie.stars, limit=15),
            "runtime": _imdb_list_to_str(movie.duration),
            "countries": _imdb_list_to_str(movie.countries),
            "certificates": _imdb_list_to_str(movie.certificates),
            "languages": _imdb_list_to_str(movie.languages),
            "director": _imdb_list_to_str(movie.directors),
            "writer": _imdb_list_to_str(movie.writers),
            "producer": _imdb_list_to_str(movie.producers),
            "composer": _imdb_list_to_str(movie.composers),
            "cinematographer": _imdb_list_to_str(
                movie.cinematographers
            ),
            "music_team": _imdb_list_to_str(movie.music_team),
            "distributors": _imdb_list_to_str(movie.distributors),
            "release_date": release_date,
            "year": movie.year,
            "genres": _imdb_list_to_str(movie.genres),
            "poster": movie.cover_url,
            "poster_url": movie.cover_url,
            "backdrop_url": None,
            "plot": plot,
            "tagline": None,
            "rating": str(movie.rating),
            "url": (
                movie.url
                or f"https://www.imdb.com/title/{normalized_imdb_id}"
            ),
            "images": {},
        }

    except Exception:
        logger.exception("IMDb lookup failed for %r", query)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_movie_details(
    query: str,
    *,
    id: bool = False,
    file: Optional[str] = None,
    provider: str = "tmdb",
) -> Optional[dict[str, Any]]:
    """
    Main movie metadata API.

    ``provider="tmdb"``:
        TMDB first, IMDb fallback.

    ``provider="imdb"``:
        IMDb only.

    ``id`` is retained for compatibility.  TMDB IDs/IMDb IDs can be supplied
    but normal title search is recommended for the new architecture.
    """
    query = str(query or "").strip()

    if not query:
        return None

    provider = provider.lower().strip()

    if provider == "imdb":
        return await get_imdb_details(
            query,
            imdb_id=id,
            file=file,
        )

    try:
        data = await fetch_tmdb_data(
            query,
            api_key=TMDB_API_KEY or None,
        )

        if data:
            return normalize_movie_data(data)

    except Exception:
        logger.exception(
            "TMDB lookup failed for %r; using IMDb fallback",
            query,
        )

    return await get_imdb_details(
        query,
        imdb_id=id,
        file=file,
    )


async def get_movie_detailsx(
    query: str,
    id: bool = False,
    file: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Compatibility alias for the old bot's TMDB-first API."""
    return await get_movie_details(
        query,
        id=id,
        file=file,
        provider="tmdb",
    )


def normalize_movie_data(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Normalize TMDB data into the shape expected by captions/templates.

    Lists are kept as lists here. Presentation code can format them later.
    """
    def split_field(value: Any) -> list[str]:
        if not value:
            return []

        if isinstance(value, list):
            return [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

        return [
            item.strip()
            for item in str(value).split(",")
            if item.strip()
        ]

    rating = _safe_float(data.get("rating"))

    normalized = {
        "title": data.get("title") or data.get("localized_title"),
        "year": data.get("year"),
        "release_date": data.get("release_date"),
        "rating": round(rating, 1) if rating is not None else None,
        "votes": _safe_int(data.get("votes")),
        "runtime": data.get("runtime"),
        "certificates": data.get("certificates"),
        "tmdb_url": data.get("url"),
        "tmdb_id": data.get("tmdb_id"),
        "imdb_id": data.get("imdb_id"),
        "genres": split_field(data.get("genres")),
        "languages": split_field(data.get("languages")),
        "countries": split_field(data.get("countries")),
        "director": split_field(data.get("director")),
        "writer": split_field(data.get("writer")),
        "producer": split_field(data.get("producer")),
        "composer": split_field(data.get("composer")),
        "cinematographer": split_field(
            data.get("cinematographer")
        ),
        "cast": split_field(data.get("cast")),
        "distributors": split_field(
            data.get("distributors")
        ),
        "plot": data.get("plot"),
        "tagline": data.get("tagline"),
        "box_office": data.get("box_office"),
        "seasons": data.get("seasons"),
        "episodes": data.get("episodes"),
        "poster_url": data.get("poster_url"),
        "backdrop_url": data.get("backdrop_url"),
        "images": data.get("images", {}),
    }

    # Keep the old template's broad compatibility fields.
    normalized["aka"] = (
        data.get("aka")
        or ""
    )
    normalized["kind"] = (
        "movie"
        if data.get("media_type") == "movie"
        else "tv series"
    )
    normalized["localized_title"] = data.get(
        "localized_title"
    )

    # Old callers sometimes expect these.
    normalized["poster"] = normalized["poster_url"]
    normalized["url"] = data.get("url")

    return normalized


async def search_movies(
    query: str,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Return multiple TMDB search candidates.

    This is intentionally separate from ``get_movie_details`` so UI code can
    offer a selection list instead of automatically taking the first match.
    """
    title, requested_year = extract_title_and_year(query)

    if not title:
        return []

    response = await tmdb_get(
        "search/multi",
        params={
            "query": title,
            "language": "en-US",
            "page": 1,
            "include_adult": "false",
        },
        api_key=TMDB_API_KEY or None,
    )

    candidates = []

    for item in response.get("results", []):
        media_type = item.get("media_type")

        if media_type not in {"movie", "tv"}:
            continue

        item_title = item.get("title") or item.get("name")
        release_date = (
            item.get("release_date")
            or item.get("first_air_date")
        )

        year = _year_from_date(release_date)

        if requested_year and year:
            if abs(int(year) - requested_year) > 1:
                continue

        candidates.append({
            "id": item.get("id"),
            "media_type": media_type,
            "title": item_title,
            "year": year,
            "overview": item.get("overview"),
            "poster_url": (
                f"{TMDB_IMAGE_W1280_URL}{item['poster_path']}"
                if item.get("poster_path")
                else None
            ),
            "backdrop_url": (
                f"{TMDB_IMAGE_W1280_URL}{item['backdrop_path']}"
                if item.get("backdrop_path")
                else None
            ),
            "rating": item.get("vote_average"),
            "votes": item.get("vote_count"),
            "similarity": title_similarity(
                item_title,
                title,
            ),
        })

    candidates.sort(
        key=lambda item: (
            item["similarity"],
            item["votes"] or 0,
        ),
        reverse=True,
    )

    return candidates[:(
        int(limit)
        if limit is not None
        else MAX_LIST_ELM
    )]


__all__ = [
    "TMDB_BASE_URL",
    "TMDB_IMAGE_BASE_URL",
    "close_session",
    "extract_title_and_year",
    "fetch_image",
    "fetch_media_details",
    "fetch_tmdb_data",
    "get_imdb_details",
    "get_movie_details",
    "get_movie_detailsx",
    "get_session",
    "normalize_movie_data",
    "normalize_title",
    "process_images",
    "search_media_id",
    "search_movies",
    "select_backdrop",
    "select_poster",
    "title_similarity",
    "tmdb_get",
]
