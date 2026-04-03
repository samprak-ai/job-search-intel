"""Role-based discovery service.

Searches for jobs by title/skill keywords across the open market,
not limited to the target company list. Complements company-based
discovery by catching roles at companies we haven't pre-selected.

Uses web search (Serper → Brave) with ATS site filters to find
real postings, then deduplicates and scores against the profile.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.config import get_settings, get_supabase_client, load_profile
from app.services.web_search import web_search
from app.services.discovery import is_junk_role
from app.services.scoring import score_role

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search query templates
# ---------------------------------------------------------------------------

# ATS sites where real job postings live
ATS_SITE_FILTER = (
    "site:greenhouse.io OR site:lever.co OR site:ashbyhq.com OR "
    "site:jobs.lever.co OR site:boards.greenhouse.io"
)

# Role search queries derived from profile target_role_types + adjacent terms
# Each entry is a search phrase that captures a class of roles Sam targets
ROLE_SEARCH_QUERIES = [
    # Core target roles
    '"AI Solutions Engineer"',
    '"AI Partnerships" OR "AI Partner"',
    '"Head of AI" product',
    '"GTM" "AI" strategy',
    # Adjacent high-value roles
    '"Solutions Architect" AI',
    '"Forward Deployed Engineer"',
    '"Applied AI" engineer OR lead',
    '"Technical Account Manager" AI',
    '"Sales Engineer" AI OR "ML"',
    '"Product Manager" AI OR "machine learning"',
    '"Business Development" AI OR "artificial intelligence"',
    '"Customer Engineer" AI OR cloud',
    '"Solutions Engineer" AI OR ML',
    '"AI evangelist" OR "developer advocate" AI',
    '"Strategic Partnerships" AI OR ML',
]


def _extract_company_from_url(url: str) -> str:
    """Best-effort company name extraction from ATS URL.

    Examples:
        boards.greenhouse.io/anthropic/... → Anthropic
        jobs.lever.co/openai/... → Openai
        jobs.ashbyhq.com/notion/... → Notion
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    if not path_parts:
        return "Unknown"

    slug = path_parts[0]

    # Clean up the slug into a readable name
    # "scaleai" → "Scaleai", "weights-and-biases" → "Weights And Biases"
    name = slug.replace("-", " ").replace("_", " ").title()
    return name


def _is_ats_job_url(url: str) -> bool:
    """Check if URL is from a known ATS platform (real job posting)."""
    host = (urlparse(url).hostname or "").lower()
    return any(ats in host for ats in [
        "greenhouse.io", "lever.co", "ashbyhq.com",
    ])


def _detect_source(url: str) -> str:
    """Detect the ATS source from URL."""
    host = (urlparse(url).hostname or "").lower()
    if "greenhouse" in host:
        return "greenhouse"
    if "lever" in host:
        return "lever"
    if "ashby" in host:
        return "ashby"
    if "linkedin" in host:
        return "linkedin"
    return host


async def discover_by_role() -> dict:
    """Discover roles by searching for job title keywords across the market.

    Returns a summary dict with counts of new roles found.
    """
    settings = get_settings()
    supabase = get_supabase_client()

    all_results = []
    queries_run = 0

    for query_phrase in ROLE_SEARCH_QUERIES:
        full_query = f"{query_phrase} ({ATS_SITE_FILTER})"
        try:
            results = await web_search(
                full_query,
                serper_api_key=settings.serper_api_key,
                brave_api_key=settings.brave_api_key,
                count=20,
                caller="role_discovery",
            )
            all_results.extend(results)
            queries_run += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Role search failed for '{query_phrase}': {e}")

    if not all_results:
        return {
            "status": "completed",
            "source": "role_discovery",
            "queries_run": queries_run,
            "raw_results": 0,
            "new_roles": 0,
        }

    # Deduplicate by URL within this batch
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_results.append(r)

    # Build role records — only keep ATS URLs (real job postings)
    roles = []
    for result in unique_results:
        url = result.get("url", "")
        title = result.get("title", "")
        description = result.get("description", "")

        if not url or not title:
            continue

        # Only keep real ATS job postings
        if not _is_ats_job_url(url):
            continue

        # Normalize URL
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Extract company name from ATS URL
        company = _extract_company_from_url(url)

        # Apply junk filters
        junk, reason = is_junk_role(title, clean_url, company, _detect_source(url))
        if junk:
            continue

        source = _detect_source(url)
        roles.append({
            "company": company,
            "title": title,
            "url": clean_url,
            "source": source,
            "raw_jd": description,
            "date_found": datetime.now(timezone.utc).isoformat(),
        })

    # Deduplicate against existing DB entries
    urls = [r["url"] for r in roles]
    if urls:
        # Batch URL check (supabase .in_ has a limit, chunk if needed)
        existing_urls = set()
        chunk_size = 100
        for i in range(0, len(urls), chunk_size):
            chunk = urls[i:i + chunk_size]
            existing = supabase.table("roles").select("url").in_("url", chunk).execute()
            existing_urls.update(r["url"] for r in existing.data)
        new_roles = [r for r in roles if r["url"] not in existing_urls]
    else:
        new_roles = []

    # Insert and auto-score
    inserted = 0
    scored = 0
    for role in new_roles:
        try:
            result_row = supabase.table("roles").insert(role).execute()
            inserted += 1

            role_id = result_row.data[0]["id"]
            try:
                await score_role(role_id)
                scored += 1
                logger.info(f"[role_discovery] Scored: {role['title']} @ {role['company']}")
            except Exception as e:
                logger.warning(f"[role_discovery] Score failed for {role['title']}: {e}")

            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"[role_discovery] Insert failed for {role['url']}: {e}")

    logger.info(
        f"Role-based discovery: {queries_run} queries, "
        f"{len(unique_results)} unique results, {len(roles)} valid, "
        f"{inserted} new, {scored} scored"
    )

    return {
        "status": "completed",
        "source": "role_discovery",
        "queries_run": queries_run,
        "raw_results": len(all_results),
        "unique_results": len(unique_results),
        "ats_matches": len(roles),
        "new_roles": inserted,
        "scored": scored,
    }
