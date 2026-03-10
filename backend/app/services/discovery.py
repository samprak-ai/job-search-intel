"""Role discovery service.

Primary path: ATS APIs (Greenhouse, Lever, Ashby) for 20/25 companies.
Fallback path: Web search (Serper → Brave) for companies without public ATS APIs.

All discovered roles are filtered for US location and relevant role keywords
before insertion.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.config import get_settings, get_supabase_client, load_companies, load_profile
from app.services.ats_clients import fetch_jobs_from_ats, filter_jobs_for_profile
from app.services.web_search import web_search
from app.services.scoring import score_role

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quality filters — shared by discovery + cleanup
# ---------------------------------------------------------------------------

JUNK_URL_SEGMENTS = {
    "/blog/", "/resources/", "/guide/", "/guides/", "/webinar/",
    "/podcast/", "/event/", "/events/", "/news/", "/press/",
    "/report/", "/reports/", "/case-study/", "/case-studies/",
    "/whitepaper/", "/ebook/", "/newsletter/",
}

JUNK_TITLE_SIGNALS = [
    "ways ", "guide", " tour", "how to", " tips", "blog", "newsroom",
    "news", "report", "webinar", "podcast", "event", "conference",
    "summit", "review", "comparison", " vs ", "what is", "top ",
    "best ", "why ", "leverage", "ultimate guide", "updates and product",
    "reasons ", "tools for", "tools to", "use ai", "definition",
    "the comprehensive", "better manage", "tech tour",
    "q1 ", "q2 ", "q3 ", "q4 ",
    "announcing", "introducing", "meet our", "meet the",
    "partner awards", "product update", "sneak peek",
    "unlocking", "stay ahead", "building what",
    "what i learned", "apollo vs", "beyond outreach",
]

# Matches "27,000+ ... jobs", "1000+ ... jobs", "154,000+ jobs", etc.
AGGREGATION_RE = re.compile(r"\d[\d,]*\+?\s+.*?\bjobs?\b", re.IGNORECASE)


ATS_SOURCES = {"greenhouse", "ashby", "lever"}


def is_junk_role(title: str, url: str, company_name: str, source: str = "") -> tuple[bool, str]:
    """Master filter: returns (is_junk, reason).

    ATS-sourced roles (greenhouse, ashby, lever) only get light filtering
    (URL path + title signals). Brave Search results get full filtering
    including misattributed-company checks.
    """
    path = urlparse(url).path.lower()
    if any(seg in path for seg in JUNK_URL_SEGMENTS):
        return True, "non-job URL (blog/resource/marketing)"

    lower = title.lower()
    if AGGREGATION_RE.search(lower):
        return True, "aggregation page"
    if any(signal in lower for signal in JUNK_TITLE_SIGNALS):
        return True, "non-job title"

    # Generic job listing pages (e.g., "Plaid jobs", "Aircall jobs")
    if re.match(r"^[\w\s.]+\bjobs\b$", lower.strip()):
        return True, "generic job listing page"

    # --- Brave Search-only checks below ---
    # ATS-sourced roles are guaranteed to belong to the correct company,
    # so skip misattribution filters for them.
    if source.lower() in ATS_SOURCES:
        return False, ""

    # LinkedIn search result pages (not actual job postings)
    if "linkedin.com/jobs/search" in url.lower() or "linkedin.com/jobs/" in url.lower():
        if "/jobs/view/" not in url.lower():
            return True, "LinkedIn search/aggregation page"

    # Misattributed roles — titles like "OtherCo hiring Role at OtherCo"
    if " hiring " in lower and company_name.lower() not in lower:
        return True, "role at a different company"

    # Pattern: "CompanyName - Role Title" where CompanyName isn't our target
    if " - " in title:
        parts = title.split(" - ", 1)
        first = parts[0].strip()
        if (
            len(first.split()) <= 5
            and company_name.lower() not in first.lower()
            and not any(
                kw in first.lower()
                for kw in ["job application", "senior", "staff", "lead", "head",
                           "vp", "director", "manager", "engineer", "scientist",
                           "analyst", "specialist", "coordinator", "associate",
                           "principal", "architect", "consultant", "advisor",
                           "ai ", "ml ", "product", "sales", "account", "business",
                           "marketing", "growth", "strategy", "data", "research",
                           "software", "solutions", "technical", "customer"]
            )
        ):
            return True, "role belongs to a different company"

    return False, ""


# ---------------------------------------------------------------------------
# ATS-based discovery (primary path)
# ---------------------------------------------------------------------------

async def discover_via_ats(company: dict) -> dict:
    """Discover roles via direct ATS API. Returns a summary dict."""
    supabase = get_supabase_client()
    company_name = company["name"]
    platform = company["ats_platform"]
    slug = company["ats_slug"]

    logger.info(f"Fetching {platform} jobs for {company_name} (slug: {slug})")

    # Fetch all jobs from ATS
    all_jobs = await fetch_jobs_from_ats(platform, slug)
    if not all_jobs:
        return {
            "company": company_name,
            "source": platform,
            "total_on_board": 0,
            "matched_filters": 0,
            "new_roles": 0,
        }

    # Filter for US location + relevant role keywords
    matched = filter_jobs_for_profile(all_jobs)

    if not matched:
        return {
            "company": company_name,
            "source": platform,
            "total_on_board": len(all_jobs),
            "matched_filters": 0,
            "new_roles": 0,
        }

    # Map ATS source to our source field
    source_name = platform  # "greenhouse", "ashby", "lever"

    # Build role records
    roles = []
    for job in matched:
        url = job["url"]
        if not url:
            continue

        # Normalize URL
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        roles.append({
            "company": company_name,
            "title": job["title"],
            "url": clean_url,
            "source": source_name,
            "raw_jd": job.get("raw_jd", ""),
            "department": job.get("department", ""),
            "date_found": datetime.now(timezone.utc).isoformat(),
        })

    # Deduplicate against existing DB entries
    urls = [r["url"] for r in roles]
    existing = supabase.table("roles").select("url").in_("url", urls).execute()
    existing_urls = {r["url"] for r in existing.data}
    new_roles = [r for r in roles if r["url"] not in existing_urls]

    # Insert and auto-score
    inserted = 0
    scored = 0
    for role in new_roles:
        try:
            result = supabase.table("roles").insert(role).execute()
            inserted += 1

            # Auto-score against profile
            role_id = result.data[0]["id"]
            try:
                await score_role(role_id)
                scored += 1
                logger.info(f"Auto-scored {role['title']}")
            except Exception as e:
                logger.warning(f"Auto-scoring failed for {role['title']}: {e}")

        except Exception as e:
            logger.warning(f"Skipping role {role['url']}: {e}")

    if inserted:
        logger.info(
            f"Inserted {inserted} new roles for {company_name} via {platform}, "
            f"scored {scored}"
        )

    return {
        "company": company_name,
        "source": platform,
        "total_on_board": len(all_jobs),
        "matched_filters": len(matched),
        "new_roles": inserted,
        "scored": scored,
        "skipped_duplicates": len(new_roles) - inserted + (len(matched) - len(new_roles)),
    }


# ---------------------------------------------------------------------------
# Brave Search fallback (for companies without ATS APIs)
# ---------------------------------------------------------------------------

def _build_brave_query(company: dict) -> str:
    """Build a focused Brave Search query for a company without ATS API."""
    company_name = company["name"]
    careers_domain = urlparse(company["careers_url"]).netloc

    role_keywords = (
        '"AI" OR "solutions engineer" OR "product manager" OR '
        '"partnerships" OR "GTM" OR "sales engineer"'
    )

    # For large companies with proprietary ATS, search broadly (LinkedIn + careers site)
    # instead of restricting to ATS platforms they don't use
    site_filter = (
        f"site:linkedin.com/jobs OR site:{careers_domain} OR "
        f"site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
    )

    return f'"{company_name}" ({role_keywords}) ({site_filter})'


async def discover_via_web_search(company: dict) -> dict:
    """Discover roles via web search fallback. Returns a summary dict."""
    settings = get_settings()
    supabase = get_supabase_client()
    company_name = company["name"]

    query = _build_brave_query(company)
    logger.info(f"Web search fallback for {company_name}")
    results = await web_search(
        query,
        serper_api_key=settings.serper_api_key,
        brave_api_key=settings.brave_api_key,
        caller="discovery",
    )

    if not results:
        return {
            "company": company_name,
            "source": "web_search",
            "total_on_board": 0,
            "matched_filters": 0,
            "new_roles": 0,
        }

    # Parse and filter results
    roles = []
    for result in results:
        url = result.get("url", "")
        title = result.get("title", "")
        description = result.get("description", "")

        if not url or not title:
            continue

        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        junk, reason = is_junk_role(title, clean_url, company_name)
        if junk:
            continue

        source = "linkedin" if "linkedin" in parsed.netloc else parsed.netloc
        roles.append({
            "company": company_name,
            "title": title,
            "url": clean_url,
            "source": source,
            "raw_jd": description,
            "date_found": datetime.now(timezone.utc).isoformat(),
        })

    # Deduplicate
    urls = [r["url"] for r in roles]
    if urls:
        existing = supabase.table("roles").select("url").in_("url", urls).execute()
        existing_urls = {r["url"] for r in existing.data}
        new_roles = [r for r in roles if r["url"] not in existing_urls]
    else:
        new_roles = []

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
            except Exception as e:
                logger.warning(f"Auto-scoring failed for {role['title']}: {e}")

        except Exception as e:
            logger.warning(f"Skipping role {role['url']}: {e}")

    return {
        "company": company_name,
        "source": "web_search",
        "total_on_board": len(results),
        "matched_filters": len(roles),
        "scored": scored,
        "new_roles": inserted,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def discover_for_company(company: dict) -> dict:
    """Discover roles for a single company via the best available method."""
    if company.get("ats_platform") and company.get("ats_slug"):
        return await discover_via_ats(company)
    else:
        return await discover_via_web_search(company)


async def discover_all() -> list[dict]:
    """Run role discovery for all target companies sequentially."""
    companies = load_companies()
    results = []

    for company in companies:
        summary = await discover_for_company(company)
        results.append(summary)
        # Small delay between API calls
        await asyncio.sleep(0.5)

    return results


# ---------------------------------------------------------------------------
# Cleanup — applies quality filters to existing DB data
# ---------------------------------------------------------------------------

async def cleanup_junk_roles() -> dict:
    """Scan all existing roles and remove junk entries."""
    supabase = get_supabase_client()

    result = supabase.table("roles").select("id, title, url, company, source").execute()
    all_roles = result.data

    junk_ids = []
    junk_details = []

    for role in all_roles:
        is_bad, reason = is_junk_role(
            role["title"], role["url"], role["company"], role.get("source", "")
        )
        if is_bad:
            junk_ids.append(role["id"])
            junk_details.append({
                "id": role["id"],
                "company": role["company"],
                "title": role["title"],
                "reason": reason,
            })

    deleted = 0
    batch_size = 50
    for i in range(0, len(junk_ids), batch_size):
        batch = junk_ids[i : i + batch_size]
        try:
            supabase.table("role_scores").delete().in_("role_id", batch).execute()
            supabase.table("sessions").delete().in_("role_id", batch).execute()
            supabase.table("roles").delete().in_("id", batch).execute()
            deleted += len(batch)
        except Exception as e:
            logger.error(f"Error deleting batch: {e}")

    return {
        "total_scanned": len(all_roles),
        "junk_found": len(junk_ids),
        "deleted": deleted,
        "details": junk_details,
    }


async def wipe_all_roles() -> dict:
    """Delete ALL roles, scores, and sessions. Use before a full re-discovery."""
    supabase = get_supabase_client()

    # Count before deletion
    count = supabase.table("roles").select("id", count="exact").execute()
    total = count.count or 0

    # Delete in dependency order
    supabase.table("sessions").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    supabase.table("role_scores").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    supabase.table("roles").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    logger.info(f"Wiped {total} roles and related data")
    return {"wiped": total}


# ---------------------------------------------------------------------------
# Backfill department from ATS APIs for existing roles
# ---------------------------------------------------------------------------

async def backfill_departments() -> dict:
    """Re-fetch ATS data and backfill department for existing roles.

    Matches by URL to update roles that are missing a department value.
    """
    supabase = get_supabase_client()
    companies = load_companies()

    # Get all roles missing department
    result = supabase.table("roles").select("id, url, company, department").execute()
    all_roles = result.data
    needs_backfill = [r for r in all_roles if not r.get("department")]

    if not needs_backfill:
        return {"total_roles": len(all_roles), "needed_backfill": 0, "updated": 0}

    # Group roles by company for batch processing
    by_company: dict[str, list[dict]] = {}
    for role in needs_backfill:
        by_company.setdefault(role["company"], []).append(role)

    updated = 0
    for company_name, roles in by_company.items():
        # Find the company config
        company_config = None
        for c in companies:
            if c["name"] == company_name:
                company_config = c
                break

        if not company_config or not company_config.get("ats_platform"):
            continue

        # Fetch fresh job data from ATS
        platform = company_config["ats_platform"]
        slug = company_config["ats_slug"]
        try:
            all_jobs = await fetch_jobs_from_ats(platform, slug)
        except Exception as e:
            logger.warning(f"Failed to fetch ATS data for {company_name}: {e}")
            continue

        # Build URL → department lookup
        url_to_dept: dict[str, str] = {}
        for job in all_jobs:
            job_url = job.get("url", "")
            if job_url:
                parsed = urlparse(job_url)
                clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                url_to_dept[clean] = job.get("department", "")

        # Match and update
        for role in roles:
            dept = url_to_dept.get(role["url"], "")
            if dept:
                try:
                    supabase.table("roles").update(
                        {"department": dept}
                    ).eq("id", role["id"]).execute()
                    updated += 1
                except Exception as e:
                    logger.warning(f"Failed to update department for {role['id']}: {e}")

    logger.info(f"Backfilled department for {updated}/{len(needs_backfill)} roles")
    return {
        "total_roles": len(all_roles),
        "needed_backfill": len(needs_backfill),
        "updated": updated,
    }
