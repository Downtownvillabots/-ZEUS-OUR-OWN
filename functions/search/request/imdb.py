"""
Non-blocking External IMDb Metadata Fetcher with Timeout.
"""

import aiohttp
from typing import Optional
from functions.search.request.config import IMDB_TIMEOUT_SECONDS


async def fetch_imdb_metadata(title: str, year: Optional[int] = None) -> Optional[dict[str, str]]:
    query = f"{title} {year}" if year else title
    url = f"https://v3.sg.media-imdb.com/suggestion/{query[0].lower()}/{aiohttp.helpers.quote(query)}.json"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=IMDB_TIMEOUT_SECONDS)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("d", [])
                    if results:
                        first = results[0]
                        return {
                            "imdb_id": first.get("id", ""),
                            "title": first.get("l", title),
                            "year": str(first.get("y", year or "")),
                        }
    except Exception:
        pass
    
    return None
