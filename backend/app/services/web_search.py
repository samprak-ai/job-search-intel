"""Unified web search client with usage tracking.

Default: Brave Search API.
Optional: Serper.dev (Google Search API), gated by SEARCH_PROVIDER and
SERPER_DAILY_LIMIT so paid search cannot run away during cron.

Both providers return results in a normalized format:
{
    "title": str,
    "url": str,
    "description": str,  # snippet text
}

Every query is logged to the api_usage table for cost monitoring.
"""

import logging
from datetime import datetime, timezone

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


def _daily_provider_usage(provider: str) -> int:
    """Return today's logged query count for a provider."""
    try:
        from app.config import get_supabase_client
        sb = get_supabase_client()
        today = datetime.now(timezone.utc).date().isoformat()
        result = (
            sb.table("api_usage")
            .select("id", count="exact")
            .eq("provider", provider)
            .gte("created_at", f"{today}T00:00:00+00:00")
            .execute()
        )
        return result.count or 0
    except Exception as e:
        logger.debug(f"Usage lookup failed (non-critical): {e}")
        return 0


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
    """Run a web search using the configured provider.

    Defaults to Brave. Set SEARCH_PROVIDER=serper to force Serper, or
    SEARCH_PROVIDER=auto to try Brave first and then Serper.
    Returns normalized results with 'title', 'url', 'description' keys.

    Args:
        caller: identifies who triggered the search ('discovery' or 'intel')
                for usage tracking.
    """
    from app.config import get_settings

    settings = get_settings()
    provider = settings.search_provider.lower().strip()
    if provider not in {"brave", "serper", "auto"}:
        logger.warning(f"Invalid SEARCH_PROVIDER={settings.search_provider!r}; using brave")
        provider = "brave"

    async def try_serper() -> list[dict] | None:
        if not serper_api_key:
            return None
        used_today = _daily_provider_usage("serper")
        if settings.serper_daily_limit >= 0 and used_today >= settings.serper_daily_limit:
            logger.warning(
                "Serper daily limit reached "
                f"({used_today}/{settings.serper_daily_limit}); skipping paid search"
            )
            _track_usage("serper", caller, query, "skipped_daily_limit")
            return None
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
        return None

    async def try_brave() -> list[dict] | None:
        if not brave_api_key:
            return None
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
        return None

    if provider == "brave":
        results = await try_brave()
        if results is not None:
            return results
    elif provider == "serper":
        results = await try_serper()
        if results is not None:
            return results
    else:
        results = await try_brave()
        if results is not None:
            return results
        results = await try_serper()
        if results is not None:
            return results

    logger.error("No search provider available (both Serper and Brave failed or unconfigured)")
    return []
