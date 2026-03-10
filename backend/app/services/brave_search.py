import logging

import httpx

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


async def search_brave(query: str, api_key: str, count: int = 20) -> list[dict]:
    """Execute a Brave Search query and return web results."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": count}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("web", {}).get("results", [])
            logger.info(f"Brave Search returned {len(results)} results for: {query[:80]}")
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"Brave Search API error {e.response.status_code}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Brave Search request failed: {e}")
            return []
