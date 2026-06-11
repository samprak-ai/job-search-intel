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

# Matches aggregation/listing-page titles: "27,000+ ... jobs", "1000+ jobs",
# "154,000+ jobs", "1,234 jobs in Seattle".
# Requires a real count signal — a thousands-comma OR a trailing '+' — within
# a few words of "jobs". A bare number like an Amazon "Job ID: 2873677"
# (no comma, no '+') followed by the "Amazon.jobs" site suffix must NOT match.
AGGREGATION_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3})+\+?\s+(?:\S+\s+){0,3}jobs?\b"  # comma-grouped count near 'jobs'
    r"|\b\d+\+\s+(?:\S+\s+){0,3}jobs?\b",                 # 'NNN+' count near 'jobs'
    re.IGNORECASE,
)


ATS_SOURCES = {"greenhouse", "ashby", "lever"}

NON_US_LOCATION_SIGNALS = [
    "london", "united kingdom", " uk", "dublin", "ireland",
    "paris", "france", "berlin", "germany", "amsterdam",
    "netherlands", "madrid", "spain", "zurich", "switzerland",
    "tokyo", "japan", "seoul", "korea", "singapore",
    "sydney", "australia", "melbourne", "toronto", "canada",
    "vancouver", "bengaluru", "bangalore", "india",
]


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


def looks_non_us_search_result(title: str, description: str) -> bool:
    """Best-effort guard for web-search results that lack structured location."""
    text = f" {title} {description} ".lower()
    return any(signal in text for signal in NON_US_LOCATION_SIGNALS)


# Trailing noise that search engines append to job titles:
#   "Senior PM - Job ID: 2873677 | Amazon.jobs"
#   "Product Manager | LinkedIn"
_TITLE_JOB_ID_RE = re.compile(r"\s*[-|]\s*job\s*id:?\s*\d+\b", re.IGNORECASE)
_TITLE_SITE_SUFFIX_RE = re.compile(r"\s*\|\s*[^|]+$")


def clean_search_title(title: str) -> str:
    """Strip search-engine cruft (site-name suffix, 'Job ID: NNN') from a title.

    Keeps stored titles clean so scoring and the application pipeline don't
    ingest "| Amazon.jobs" / "Job ID: 12345" noise.
    """
    t = (title or "").strip()
    t = _TITLE_SITE_SUFFIX_RE.sub("", t)   # drop ' | Amazon.jobs'
    t = _TITLE_JOB_ID_RE.sub("", t)        # drop ' - Job ID: 2873677'
    return t.strip(" -|").strip()


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

        # Normalize URL — always https, strip query/fragment
        parsed = urlparse(url)
        clean_url = f"https://{parsed.netloc}{parsed.path}"

        roles.append({
            "company": company_name,
            "title": job["title"],
            "url": clean_url,
            "source": source_name,
            "raw_jd": job.get("raw_jd", ""),
            "department": job.get("department", ""),
            "date_found": datetime.now(timezone.utc).isoformat(),
        })

    # ── Dedup Step 1: URL check against DB ───────────────────────────
    urls = [r["url"] for r in roles]
    existing_url_result = supabase.table("roles").select("url").in_("url", urls).execute()
    existing_urls = {r["url"] for r in existing_url_result.data}

    # ── Dedup Step 2: (company, title) check against DB ──────────────
    # Catches the same role posted under multiple ATS requisition IDs
    # (e.g., multiple headcount for "PM, Growth") and http/https variants
    # that slipped through URL normalization.
    url_filtered = [r for r in roles if r["url"] not in existing_urls]
    candidate_titles = list({r["title"] for r in url_filtered})
    existing_title_set: set[str] = set()
    if candidate_titles:
        title_result = (
            supabase.table("roles")
            .select("title")
            .eq("company", company_name)
            .in_("title", candidate_titles)
            .execute()
        )
        existing_title_set = {r["title"].lower().strip() for r in title_result.data}

    # ── Dedup Step 3: within-batch title dedup (first URL wins) ──────
    seen_titles: set[str] = set()
    new_roles = []
    for r in url_filtered:
        t = r["title"].lower().strip()
        if t in existing_title_set or t in seen_titles:
            continue
        seen_titles.add(t)
        new_roles.append(r)

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

    # NOTE: Amazon does NOT use this Brave path — it's routed through the
    # structured amazon.jobs ATS client (fetch_amazon_jobs in ats_clients.py),
    # which filters precisely on Seattle + AWS/AGI org via the search.json API.

    # Google (broader than DeepMind, which has its own Greenhouse board). No
    # clean ATS, so scope tightly to google.com/about/careers + LinkedIn job
    # views with PM/AI/GTM keywords — searching the bare name is too noisy.
    if company_name.lower() == "google":
        role_keywords = (
            '"Product Manager" OR "Head of Product" OR "Applied AI" OR '
            '"Product Lead" OR "GTM"'
        )
        us = '"United States" OR "Mountain View" OR "New York" OR "Seattle"'
        return (
            f"Google ({role_keywords}) "
            f"(site:google.com/about/careers OR site:linkedin.com/jobs/view) ({us})"
        )

    role_keywords = (
        '"AI" OR "solutions engineer" OR "product manager" OR '
        '"partnerships" OR "GTM" OR "sales engineer"'
    )
    us_location_filter = (
        '"United States" OR "USA" OR "US" OR "San Francisco" OR '
        '"New York" OR "Seattle"'
    )

    # For large companies with proprietary ATS, search broadly (LinkedIn + careers site)
    # instead of restricting to ATS platforms they don't use
    site_filter = (
        f"site:linkedin.com/jobs OR site:{careers_domain} OR "
        f"site:greenhouse.io OR site:lever.co OR site:ashbyhq.com"
    )

    return f'"{company_name}" ({role_keywords}) ({us_location_filter}) ({site_filter})'


# Regex patterns that match URLs which look like individual job postings.
# A URL must match at least one of these to be considered a real job listing.
# Generic non-job paths like /agentforce/, /partners/, /company/careers/ won't match.
import re as _re

_JOB_URL_PATTERNS = [
    # Path with /jobs/<id>/ followed by optional slug (e.g. Salesforce, generic ATS)
    _re.compile(r"/jobs?/[a-z][a-z0-9_-]{1,}(/[a-z0-9._-]+)*/?$", _re.I),
    _re.compile(r"/jobs?/view/\d+", _re.I),                          # LinkedIn /jobs/view/12345
    # Numeric job IDs (Amazon amazon.jobs/en/jobs/2812345/slug, and similar
    # proprietary boards). Requires 5+ digits to avoid matching years/pages.
    _re.compile(r"/jobs?/\d{5,}", _re.I),
    _re.compile(r"/careers/(jobs?|positions?|openings?)/[a-z0-9]", _re.I),
    _re.compile(r"/positions?/[a-z0-9]", _re.I),
    _re.compile(r"/openings?/[a-z0-9]", _re.I),
    _re.compile(r"/listings?/[a-z0-9]", _re.I),
    _re.compile(r"boards\.greenhouse\.io/[^/]+/jobs/\d+", _re.I),
    _re.compile(r"jobs\.lever\.co/[^/]+/[a-f0-9-]{8,}", _re.I),
    _re.compile(r"jobs\.ashbyhq\.com/[^/]+/[a-f0-9-]{8,}", _re.I),
]

# Hard-reject URL patterns — paths that contain "jobs" but aren't individual postings.
_JOB_URL_BLOCKLIST = [
    _re.compile(r"/(xml|rss|atom|feed|sitemap)\b", _re.I),
    _re.compile(r"\.(xml|rss|atom|json)(\?|$)", _re.I),
    _re.compile(r"/jobs?/?$", _re.I),                                # bare /jobs/ index
    _re.compile(r"/jobs?/(search|category|department|all|index)\b", _re.I),
]

# Title patterns that indicate a landing page rather than an individual posting.
_LANDING_TITLE_PATTERNS = [
    _re.compile(r"^\s*careers?\b", _re.I),
    _re.compile(r"\bcareers?\s*[|\-]\s*", _re.I),                    # "X Careers | Company"
    _re.compile(r"\bcareers?\s+at\b", _re.I),                        # "Tech & Product Careers at Salesforce"
    _re.compile(r"\b(team|teams|department)\s*[|\-]", _re.I),
    _re.compile(r"\bbuild\s+(what|the\s+future|with)\b", _re.I),     # "Build What's Next", "Build the Future"
    _re.compile(r"\b(get\s+ai\s+working|the\s+ai\s+agent\s+platform)\b", _re.I),  # Salesforce product pages
    _re.compile(r"^https?://", _re.I),                               # Title looks like a URL
    _re.compile(r"\.(xml|rss|atom)\b", _re.I),
]


def _is_likely_job_posting_url(url: str) -> bool:
    """Return True if URL path looks like an individual job posting."""
    parsed = urlparse(url)
    full = f"{parsed.netloc}{parsed.path}"
    # Hard-reject patterns short-circuit even if a positive pattern matches
    if any(p.search(full) for p in _JOB_URL_BLOCKLIST):
        return False
    return any(p.search(full) for p in _JOB_URL_PATTERNS)


def _looks_like_landing_title(title: str) -> bool:
    """Return True if title looks like a careers/landing page rather than a specific role."""
    return any(p.search(title or "") for p in _LANDING_TITLE_PATTERNS)


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
    rejected_landing = 0
    rejected_url_pattern = 0
    for result in results:
        url = result.get("url", "")
        title = clean_search_title(result.get("title", ""))
        description = result.get("description", "")

        if not url or not title:
            continue

        if looks_non_us_search_result(title, description):
            continue

        # Reject obvious landing-page / non-posting URLs and titles. This
        # prevents pages like /agentforce/, /partners/, /careers/ (without a
        # specific job id), or RSS feeds from getting scored as jobs.
        if not _is_likely_job_posting_url(url):
            rejected_url_pattern += 1
            continue
        if _looks_like_landing_title(title):
            rejected_landing += 1
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

    if rejected_url_pattern or rejected_landing:
        logger.info(
            f"Web search for {company_name}: rejected "
            f"{rejected_url_pattern} non-job URLs, "
            f"{rejected_landing} landing-page titles"
        )

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
