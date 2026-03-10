"""Unified web search client with usage tracking.

Primary: Serper.dev (Google Search API) — fast, cheap, reliable.
Fallback: Brave Search API — if configured, used when Serper is unavailable.

Both providers return results in a normalized format:
{
    "title": str,
    "url": str,
    "description": str,  # snippet text
}

Every query is logged to the api_usage table for cost monitoring.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def _track_usage(
    provider: str,
    caller: str,
    query: str,
    status: str,
    result_count: int = 0,
) -> None:
    """Fire-and-forget usage tracking to Supabase.

    Non-blocking: errors are swallowed so tracking never breaks search.
    """
    try:
        from app.config import get_supabase_client
        sb = get_supabase_client()
        sb.table("api_usage").insert({
            "provider": provider,
            "caller": caller,
            "query_preview": query[:120],
            "status": status,
            "result_count": result_count,
        }).execute()
    except Exception as e:
        logger.debug(f"Usage tracking failed (non-critical): {e}")


async def _search_serper(query: str, api_key: str, count: int) -> list[dict]:
    """Execute a search via Serper.dev (Google results)."""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": count}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            SERPER_URL, headers=headers, json=payload, timeout=15.0
        )
        response.raise_for_status()
        data = response.json()

    # Normalize Serper response — organic results use "title", "link", "snippet"
    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": item.get("snippet", ""),
        })

    logger.info(f"Serper returned {len(results)} results for: {query[:80]}")
    return results


async def _search_brave(query: str, api_key: str, count: int) -> list[dict]:
    """Execute a search via Brave Search API (fallback)."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": count}

    async with httpx.AsyncClient() as client:
        response = await client.get(
            BRAVE_URL, headers=headers, params=params, timeout=15.0
        )
        response.raise_for_status()
        data = response.json()

    # Normalize Brave response — web results use "title", "url", "description"
    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
        })

    logger.info(f"Brave returned {len(results)} results for: {query[:80]}")
    return results


async def web_search(
    query: str,
    serper_api_key: str = "",
    brave_api_key: str = "",
    count: int = 20,
    caller: str = "unknown",
) -> list[dict]:
    """Run a web search using the best available provider.

    Tries Serper first (if key provided), falls back to Brave.
    Returns normalized results with 'title', 'url', 'description' keys.

    Args:
        caller: identifies who triggered the search ('discovery' or 'intel')
                for usage tracking.
    """
    # Try Serper first
    if serper_api_key:
        try:
            results = await _search_serper(query, serper_api_key, count)
            _track_usage("serper", caller, query, "success", len(results))
            return results
        except httpx.HTTPStatusError as e:
            logger.warning(f"Serper API error {e.response.status_code}: {e}")
            _track_usage("serper", caller, query, f"error_{e.response.status_code}")
        except httpx.RequestError as e:
            logger.warning(f"Serper request failed: {e}")
            _track_usage("serper", caller, query, "error_request")

    # Fall back to Brave
    if brave_api_key:
        try:
            results = await _search_brave(query, brave_api_key, count)
            _track_usage("brave", caller, query, "success", len(results))
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"Brave API error {e.response.status_code}: {e}")
            _track_usage("brave", caller, query, f"error_{e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Brave request failed: {e}")
            _track_usage("brave", caller, query, "error_request")

    logger.error("No search provider available (both Serper and Brave failed or unconfigured)")
    return []
