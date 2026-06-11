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
LISTING_TIMEOUT = 45.0  # Bulk-board fetches can be large (e.g. OpenAI has 600+ jobs)

# Regex patterns to extract job IDs from ATS URLs
GREENHOUSE_ID_RE = re.compile(r"greenhouse\.io/.*?/jobs/(\d+)")
LEVER_ID_RE = re.compile(r"lever\.co/([^/]+)/([a-f0-9-]+)")
ASHBY_ID_RE = re.compile(r"ashbyhq\.com/([^/]+)/([a-f0-9-]+)")

# HTTP statuses that definitively mean the posting is gone. 403 is deliberately
# EXCLUDED: sites like Google Careers and LinkedIn return 403 to bot/rapid
# traffic (rate-limiting), which is inconclusive — not a removed posting. A
# burst freshness sweep that treated 403 as dead would wrongly mark live roles
# stale (it did, to Google Careers roles). 403/429 now fall through to None.
DEAD_STATUSES = {404, 410}


async def _check_greenhouse(url: str) -> bool | None:
    """Check if a Greenhouse job posting is still live.

    Uses the bulk board listing API (not per-job) because per-job endpoints
    can return 200 for jobs that have been pulled from the public board.
    The bulk listing reflects the *actual* current public state.
    """
    match = GREENHOUSE_ID_RE.search(url)
    if not match:
        return None  # Can't parse, fall back to HTTP

    job_id = match.group(1)
    slug_match = re.search(r"greenhouse\.io/([^/]+)/jobs/", url)
    if not slug_match:
        return None

    slug = slug_match.group(1)
    listing_ids = await _get_greenhouse_listing(slug)
    if listing_ids is None:
        return None  # Couldn't fetch listing, inconclusive
    return job_id in listing_ids


# Per-process cache of full board listings, keyed by ATS+slug.
# Populated lazily on first lookup; reused across all roles in a freshness run.
# Format: {("greenhouse", slug): {job_id, ...}, ("ashby", slug): {job_id, ...}}
_LISTING_CACHE: dict[tuple[str, str], set[str] | None] = {}


async def _get_greenhouse_listing(slug: str) -> set[str] | None:
    """Fetch the full set of public Greenhouse job IDs for a board slug."""
    cache_key = ("greenhouse", slug)
    if cache_key in _LISTING_CACHE:
        return _LISTING_CACHE[cache_key]

    api_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, timeout=LISTING_TIMEOUT)
            if resp.status_code == 200:
                ids = {str(j["id"]) for j in resp.json().get("jobs", [])}
                _LISTING_CACHE[cache_key] = ids
                return ids
    except Exception as e:
        logger.debug(f"Greenhouse bulk listing failed for {slug}: {e}")
    _LISTING_CACHE[cache_key] = None
    return None


async def _get_ashby_listing(slug: str) -> set[str] | None:
    """Fetch the full set of public Ashby posting IDs for a board slug."""
    cache_key = ("ashby", slug)
    if cache_key in _LISTING_CACHE:
        return _LISTING_CACHE[cache_key]

    api_url = (
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        f"?includeCompensation=false"
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(api_url, timeout=LISTING_TIMEOUT)
            if resp.status_code == 200:
                ids = {j["id"] for j in resp.json().get("jobs", [])}
                _LISTING_CACHE[cache_key] = ids
                return ids
    except Exception as e:
        logger.debug(f"Ashby bulk listing failed for {slug}: {e}")
    _LISTING_CACHE[cache_key] = None
    return None


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

    Uses the bulk job-board listing (the source of truth for what's
    publicly accepting applications). Per-job page checks are unreliable
    because the page renders even for jobs that have been pulled from
    the public board.
    """
    match = ASHBY_ID_RE.search(url)
    if not match:
        return None

    slug = match.group(1)
    posting_id = match.group(2)

    listing_ids = await _get_ashby_listing(slug)
    if listing_ids is None:
        return None  # Couldn't fetch listing, inconclusive
    return posting_id in listing_ids


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


_CLOSED_BODY_SIGNALS = [
    "no longer accepting applications",
    "this job has been closed",
    "position has been filled",
    "this requisition is closed",
    "we are no longer accepting",
    "job not found",
    "this position is no longer available",
    "this position is no longer open",
    "job no longer available",
    "page not found",
]


async def _check_http(url: str) -> bool | None:
    """Generic HTTP check with content-signal awareness.

    Status-based: 404/410/403 → stale. 2xx → continue to content check.
    Content-based: GET the page and scan body for closed-job phrases. Catches
    proprietary careers sites (google careers, salesforce careers, etc.) that
    render a 200 OK shell even when the underlying listing has been pulled.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Always GET (not HEAD) so we can inspect body content.
            # HEAD doesn't return a body, so content-signal check is impossible.
            resp = await client.get(url, headers=headers, timeout=CHECK_TIMEOUT)
            if resp.status_code in DEAD_STATUSES:
                return False
            if resp.status_code >= 400:
                return None  # Server error etc — don't conclude
            # Content-signal check on the body
            body = (resp.text or "").lower()
            for signal in _CLOSED_BODY_SIGNALS:
                if signal in body:
                    logger.info(f"Stale detected via content signal '{signal}' on {url}")
                    return False
            # Page loaded clean with no closed signals
            return True
    except (httpx.TimeoutException, httpx.ConnectError):
        logger.debug(f"Timeout/connection error checking {url}")
        return None  # Transient — don't flag
    except Exception as e:
        logger.debug(f"HTTP check failed for {url}: {e}")
        return None


async def _check_amazon(url: str) -> bool | None:
    """Check if an amazon.jobs posting is still live.

    Amazon hard-404s expired postings, so 404/410 is a reliable "gone" signal.
    But amazon.jobs also bot-throttles with 403/429 under rapid requests — those
    must stay INCONCLUSIVE (None), or a throttled freshness sweep would wrongly
    mark live roles stale. (The generic _check_http treats 403 as dead, which is
    wrong for Amazon — hence this dedicated check.)
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, timeout=CHECK_TIMEOUT)
            if resp.status_code in (404, 410):
                return False
            if resp.status_code == 200:
                body = (resp.text or "").lower()
                for signal in _CLOSED_BODY_SIGNALS:
                    if signal in body:
                        return False
                return True
            return None  # 403/429/5xx → throttled or transient, don't conclude
    except (httpx.TimeoutException, httpx.ConnectError):
        return None
    except Exception as e:
        logger.debug(f"Amazon freshness check failed for {url}: {e}")
        return None


async def _check_linkedin(url: str) -> bool | None:
    """Check a LinkedIn posting via the public guest job endpoint.

    The careers page itself blocks bots, but jobs-guest/jobPosting/{id} returns
    200 for live postings and 404/410 once a job is pulled. 403/429 = throttled
    → inconclusive (None).
    """
    m = re.search(r"/jobs/view/(?:.*-)?(\d+)", url)
    if not m:
        return None
    job_id = m.group(1)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}",
                headers=headers, timeout=CHECK_TIMEOUT,
            )
            if resp.status_code in (404, 410):
                return False
            if resp.status_code == 200:
                return True
            return None  # 403/429/5xx — throttled, inconclusive
    except (httpx.TimeoutException, httpx.ConnectError):
        return None
    except Exception as e:
        logger.debug(f"LinkedIn freshness check failed for {url}: {e}")
        return None


async def check_role_freshness(role: dict) -> dict | None:
    """Check if a single role's URL is still live.

    Returns update dict {is_live, last_checked_at} or None if inconclusive.
    """
    url = role.get("url", "")
    source = role.get("source", "")

    # Google Careers is a client-rendered SPA: a bot fetch returns 200 with a
    # generic shell for BOTH live and dead jobs, so HTTP freshness is meaningless
    # (it would either always-live or always-dead). Treat as inconclusive — these
    # roles should come from the verifiable LinkedIn source instead.
    if "google.com/about/careers" in url:
        return None

    # Try ATS-specific / source-specific checks first (more reliable)
    result = None
    if "linkedin.com" in url:
        result = await _check_linkedin(url)
    elif source == "greenhouse" or "greenhouse.io" in url:
        result = await _check_greenhouse(url)
    elif source == "lever" or "lever.co" in url:
        result = await _check_lever(url)
    elif source == "ashby" or "ashbyhq.com" in url:
        result = await _check_ashby(url)
    elif source == "amazon" or "amazon.jobs" in url:
        result = await _check_amazon(url)

    # Fall back to generic HTTP check (not for amazon.jobs / linkedin / google careers)
    if result is None and not any(s in url for s in ("amazon.jobs", "linkedin.com")):
        result = await _check_http(url)

    if result is None:
        return None  # Inconclusive, don't update

    now = datetime.now(timezone.utc).isoformat()
    return {"is_live": result, "last_checked_at": now}


def _maybe_log_stale_high_score(supabase, role_id: str) -> None:
    """If a role that just went stale had a Strong+ score, log a detected gap.

    Catches the "we surfaced/emailed a job that was already closing" class —
    the dead 'View Original' link problem. Non-blocking.
    """
    try:
        score = (
            supabase.table("role_scores")
            .select("overall_score, match_tier")
            .eq("role_id", role_id)
            .order("scored_at", desc=True)
            .limit(1)
            .execute()
        ).data
        if not score or (score[0].get("overall_score") or 0) < 80:
            return
        role = (
            supabase.table("roles").select("title, company").eq("id", role_id).execute()
        ).data
        label = (
            f"{role[0].get('title', '?')} @ {role[0].get('company', '?')}" if role else None
        )
        from app.services.gaps import log_gap

        log_gap(
            "stale_high_score",
            f"A {score[0].get('match_tier')} ({score[0].get('overall_score')}) role went dead — "
            f"it may have been surfaced or emailed while already closing.",
            severity="medium",
            role_id=role_id,
            role_label=label,
            detail={"overall_score": score[0].get("overall_score")},
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"stale_high_score gap check failed for {role_id}: {e}")


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
                    _maybe_log_stale_high_score(supabase, role["id"])
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


async def deep_scan_freshness(delete_stale: bool = True) -> dict:
    """Weekly deep-scan: more aggressive staleness detection.

    Differences vs. check_all_freshness():
    - Force-rechecks every role (clears the listing cache so bulk ATS calls
      hit the API fresh, not just first time of run).
    - After the standard check, also explicitly deletes is_live=False rows
      and their scores (if delete_stale=True) so the dashboard is purged.
    - Returns a richer summary including per-company stale counts.
    """
    supabase = get_supabase_client()

    # Force-fresh ATS listings — don't trust per-process cache from prior runs.
    _LISTING_CACHE.clear()

    summary = await check_all_freshness()

    # Pull all roles now flagged stale (this run + any prior unflagged ones)
    stale_q = supabase.table("roles").select(
        "id, company, title, url"
    ).eq("is_live", False).execute()
    stale_rows = stale_q.data or []

    from collections import Counter
    company_breakdown = dict(Counter(r["company"] for r in stale_rows))

    deleted_roles = 0
    deleted_scores = 0
    if delete_stale and stale_rows:
        ids = [r["id"] for r in stale_rows]
        chunk = 100
        for i in range(0, len(ids), chunk):
            batch = ids[i:i + chunk]
            score_del = supabase.table("role_scores").delete().in_("role_id", batch).execute()
            deleted_scores += len(score_del.data) if score_del.data else 0
            role_del = supabase.table("roles").delete().in_("id", batch).execute()
            deleted_roles += len(role_del.data) if role_del.data else 0
        logger.info(
            f"Deep scan: deleted {deleted_roles} stale roles and "
            f"{deleted_scores} role_scores"
        )

    summary["deep_scan"] = True
    summary["deleted_roles"] = deleted_roles
    summary["deleted_scores"] = deleted_scores
    summary["stale_by_company"] = company_breakdown
    return summary
