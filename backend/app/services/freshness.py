"""Freshness check service — validates whether discovered role URLs are still live.

Checks ATS API endpoints for Greenhouse/Lever/Ashby roles (more reliable),
falls back to HTTP HEAD for other URLs. Flags dead postings so the dashboard
can warn the user.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx

from app.config import get_supabase_client

logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 10.0

# Regex patterns to extract job IDs from ATS URLs
GREENHOUSE_ID_RE = re.compile(r"greenhouse\.io/.*?/jobs/(\d+)")
LEVER_ID_RE = re.compile(r"lever\.co/([^/]+)/([a-f0-9-]+)")
ASHBY_ID_RE = re.compile(r"ashbyhq\.com/([^/]+)/([a-f0-9-]+)")

# HTTP statuses that indicate the posting is gone
DEAD_STATUSES = {404, 410, 403}


async def _check_greenhouse(url: str) -> bool | None:
    """Check if a Greenhouse job posting is still live via API."""
    match = GREENHOUSE_ID_RE.search(url)
    if not match:
        return None  # Can't parse, fall back to HTTP

    job_id = match.group(1)
    # Extract the board slug from the URL path
    # e.g., https://boards.greenhouse.io/anthropic/jobs/12345
    slug_match = re.search(r"greenhouse\.io/([^/]+)/jobs/", url)
    if not slug_match:
        return None

    slug = slug_match.group(1)
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code == 200:
                return True
    except Exception as e:
        logger.debug(f"Greenhouse API check failed for {url}: {e}")
    return None  # Inconclusive


async def _check_lever(url: str) -> bool | None:
    """Check if a Lever posting is still live via API."""
    match = LEVER_ID_RE.search(url)
    if not match:
        return None

    slug, posting_id = match.group(1), match.group(2)
    api_url = f"https://api.lever.co/v0/postings/{slug}/{posting_id}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code == 200:
                return True
    except Exception as e:
        logger.debug(f"Lever API check failed for {url}: {e}")
    return None


async def _check_ashby(url: str) -> bool | None:
    """Check if an Ashby posting is still live.

    The non-auth API endpoint is not reliable for all postings —
    some live jobs return 404 from the API while the page is still active.
    When the API says 404, we fall back to checking the actual page content
    for signs of a closed posting (e.g. "no longer available" text).
    """
    match = ASHBY_ID_RE.search(url)
    if not match:
        return None

    # Ashby posting URLs: https://jobs.ashbyhq.com/{company}/{posting_id}
    posting_id = match.group(2)
    api_url = f"https://jobs.ashbyhq.com/api/non-auth-job-posting/{posting_id}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, timeout=CHECK_TIMEOUT)
            if resp.status_code == 200:
                return True
            if resp.status_code in DEAD_STATUSES:
                # API is unreliable — verify by checking actual page content
                return await _verify_ashby_page(url)
    except Exception as e:
        logger.debug(f"Ashby API check failed for {url}: {e}")
    return None


async def _verify_ashby_page(url: str) -> bool | None:
    """Verify an Ashby posting by checking the actual page for closed signals.

    Ashby renders a 200 page even for closed postings, so we check the
    response body for indicators like 'no longer available' or missing
    application form elements.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code == 200:
                body = resp.text.lower()
                # Ashby closed-posting signals
                closed_signals = [
                    "no longer available",
                    "this job has been closed",
                    "position has been filled",
                    "job not found",
                ]
                for signal in closed_signals:
                    if signal in body:
                        return False
                # Page loaded OK with no closed signals → likely still live
                return True
    except Exception as e:
        logger.debug(f"Ashby page verification failed for {url}: {e}")
    return None


async def _check_http(url: str) -> bool | None:
    """Generic HTTP check — HEAD request with redirect following."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.head(url, headers=headers, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code < 400:
                return True
            # Some servers don't support HEAD, try GET
            resp = await client.get(url, headers=headers, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code < 400:
                return True
    except (httpx.TimeoutException, httpx.ConnectError):
        logger.debug(f"Timeout/connection error checking {url}")
        return None  # Transient — don't flag
    except Exception as e:
        logger.debug(f"HTTP check failed for {url}: {e}")
        return None

    return None


async def check_role_freshness(role: dict) -> dict | None:
    """Check if a single role's URL is still live.

    Returns update dict {is_live, last_checked_at} or None if inconclusive.
    """
    url = role.get("url", "")
    source = role.get("source", "")

    # Skip LinkedIn — always blocks automated requests
    if "linkedin.com" in url:
        return None

    # Try ATS-specific checks first (more reliable)
    result = None
    if source == "greenhouse" or "greenhouse.io" in url:
        result = await _check_greenhouse(url)
    elif source == "lever" or "lever.co" in url:
        result = await _check_lever(url)
    elif source == "ashby" or "ashbyhq.com" in url:
        result = await _check_ashby(url)

    # Fall back to generic HTTP check
    if result is None:
        result = await _check_http(url)

    if result is None:
        return None  # Inconclusive, don't update

    now = datetime.now(timezone.utc).isoformat()
    return {"is_live": result, "last_checked_at": now}


async def check_all_freshness() -> dict:
    """Check freshness for all active roles.

    Skips roles with application_status in ('rejected', 'skipped').
    Returns summary stats.
    """
    supabase = get_supabase_client()

    # Fetch all roles that should be checked
    result = supabase.table("roles").select(
        "id, url, source, application_status"
    ).execute()

    all_roles = result.data
    skip_statuses = {"rejected", "skipped"}

    candidates = [
        r for r in all_roles
        if r.get("application_status") not in skip_statuses
    ]

    logger.info(
        f"Freshness check: {len(candidates)} candidates "
        f"out of {len(all_roles)} total roles"
    )

    checked = 0
    stale_found = 0
    skipped = 0
    errors = 0

    for role in candidates:
        update = await check_role_freshness(role)

        if update is None:
            skipped += 1
        else:
            try:
                supabase.table("roles").update(update).eq(
                    "id", role["id"]
                ).execute()
                checked += 1
                if not update["is_live"]:
                    stale_found += 1
                    logger.info(
                        f"Stale role detected: {role['url']}"
                    )
            except Exception as e:
                errors += 1
                logger.warning(f"Failed to update freshness for {role['id']}: {e}")

        await asyncio.sleep(0.3)

    logger.info(
        f"Freshness check complete: {checked} checked, "
        f"{stale_found} stale, {skipped} skipped, {errors} errors"
    )

    return {
        "total_roles": len(all_roles),
        "checked": checked,
        "stale_found": stale_found,
        "skipped": skipped,
        "errors": errors,
    }
