"""ATS API clients for Greenhouse, Lever, and Ashby.

Each client fetches all jobs from a company's public job board API and
normalizes them into a common format for the discovery pipeline.

Common output format per job:
{
    "title": str,
    "url": str,         # direct link to the job posting
    "location": str,    # raw location string from ATS
    "department": str,  # team/department if available
    "raw_jd": str,      # job description text (HTML stripped)
}
"""

import logging
import re
from html import unescape

import httpx

logger = logging.getLogger(__name__)

# Timeout for ATS API calls (generous — some boards are large)
ATS_TIMEOUT = 30.0

# US location keywords for filtering
US_LOCATION_KEYWORDS = [
    "united states", "usa", "us ", " us,", "(us)", "u.s.",
    "remote", "anywhere",
    "remote - us", "remote, us", "remote us", "remote (us)",
    "remote - united states", "remote, united states",
    # US states and major cities
    "california", "new york", "san francisco", "seattle", "austin",
    "boston", "chicago", "denver", "los angeles", "washington",
    "atlanta", "miami", "dallas", "houston", "portland",
    "raleigh", "nashville", "phoenix", "san diego", "minneapolis",
    "salt lake", "charlotte", "philadelphia", "pittsburgh",
    "detroit", "columbus", "indianapolis", "kansas city",
    "renton", "bellevue", "redmond", "palo alto", "mountain view",
    "sunnyvale", "menlo park", "cupertino", "san jose",
    ", ca", ", ny", ", wa", ", tx", ", ma", ", co", ", il",
    ", ga", ", fl", ", or", ", nc", ", tn", ", az", ", ut",
    ", va", ", pa", ", oh", ", mn", ", mo", ", md", ", ct",
]

NON_US_LOCATION_KEYWORDS = [
    "canada", "toronto", "vancouver", "united kingdom", " uk",
    "london", "dublin", "ireland", "france", "paris", "germany",
    "berlin", "netherlands", "amsterdam", "spain", "madrid",
    "switzerland", "zurich", "japan", "tokyo", "korea", "seoul",
    "singapore", "australia", "sydney", "melbourne", "india",
    "bengaluru", "bangalore",
]

# Role title keywords that match Sam's target profile.
# Tuned to AI product PMF assessment, product growth, incubation, and
# builder-operator roles. Engineer / Solutions Architect titles are
# explicitly excluded.
ROLE_KEYWORDS = [
    # AI product / product strategy / growth
    "ai product", "product strategy", "product growth",
    "growth product", "product lead", "product manager",
    "product manager", "product lead", "product marketing",
    "product owner", "product management",
    "head of product", "head of ai product",
    "senior product manager", "lead product manager",
    "pmt",  # Amazon abbrev: Product Manager Technical (e.g. "Sr. PMT-ES, Bedrock")
    # Applied AI / labs / incubation
    "applied ai", "ai applications", "ai automation",
    "ai agents", "agents", "labs", "incubation",
    "new products", "new bets", "strategic projects",
    # GTM systems builder roles
    "gtm systems", "gtm automation", "go-to-market systems",
    "go to market systems", "sales intelligence",
    "business systems", "ai operations", "systems and ai",
    "partner business systems",
    # Chief of staff with likely product/AI/GTM altitude
    "chief of staff",
    # Senior leadership titles are allowed only when paired with relevant text.
    "head of",
]

# Titles to explicitly EXCLUDE even if keywords match.
# Broad "engineer" and "architect" excludes catch all engineering / SA tracks
# (Software Engineer, Solutions Engineer, Sales Engineer, Solutions Architect,
# Customer Engineer, Forward Deployed Engineer, Engineering Manager, etc.)
ROLE_EXCLUDE_KEYWORDS = [
    "engineer", "engineering",
    "solutions architect", "solution architect",
    "sales engineer", "customer engineer", "forward deployed engineer",
    "account executive", "account manager", "customer success",
    "partner manager", "partner sales", "business development",
    "planning operations", "bdr operations", "sales operations",
    "revenue operations", "territory", "quota", "enablement",
    "onboarding", "implementation", "deployment",
    "finance systems", "workday", "hcm", "hris",
    "video", "recruiter", "recruiting", "counsel",
    "accounting", "accountant", "finance &",
    "supply chain", "security fellow", "safety fellow",
]

ROLE_CONTEXT_KEYWORDS = [
    "ai", "agent", "automation", "product", "growth", "strategy",
    "incubation", "labs", "0-to-1", "prototype", "customer outcomes",
    "adoption", "usage", "activation", "product-market fit",
]


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _is_us_location(location: str) -> bool:
    """Check if a location string indicates a US-based role."""
    if not location:
        return False
    lower = location.lower()
    if any(kw in lower for kw in NON_US_LOCATION_KEYWORDS):
        return False
    return any(kw in lower for kw in US_LOCATION_KEYWORDS)


def _matches_role_keywords(title: str, raw_jd: str = "", department: str = "") -> bool:
    """Check if a job title matches Sam's target role types.

    Must match at least one ROLE_KEYWORD and not match any ROLE_EXCLUDE_KEYWORDS.
    """
    lower = title.lower()
    if any(ex in lower for ex in ROLE_EXCLUDE_KEYWORDS):
        return False
    if not any(kw in lower for kw in ROLE_KEYWORDS):
        return False

    context = f"{title} {department} {raw_jd[:3000]}".lower()
    if "chief of staff" in lower or lower.startswith("head of"):
        return any(kw in context for kw in ROLE_CONTEXT_KEYWORDS)
    return True


# ---------------------------------------------------------------------------
# Greenhouse API
# ---------------------------------------------------------------------------

async def fetch_greenhouse_jobs(slug: str) -> list[dict]:
    """Fetch all jobs from a Greenhouse board API.

    API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    The `content=true` param includes the full job description HTML.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    params = {"content": "true"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=ATS_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            jobs_raw = data.get("jobs", [])
        except Exception as e:
            logger.error(f"Greenhouse API error for {slug}: {e}")
            return []

    jobs = []
    for job in jobs_raw:
        # Extract location from the first location object
        location = ""
        if job.get("location", {}).get("name"):
            location = job["location"]["name"]

        # Extract department
        department = ""
        departments = job.get("departments", [])
        if departments:
            department = departments[0].get("name", "")

        # Get job description
        content = job.get("content", "")
        raw_jd = _strip_html_tags(content) if content else ""

        # Build the posting URL
        posting_url = job.get("absolute_url", "")

        jobs.append({
            "title": job.get("title", ""),
            "url": posting_url,
            "location": location,
            "department": department,
            "raw_jd": raw_jd,
        })

    logger.info(f"Greenhouse [{slug}]: fetched {len(jobs)} jobs")
    return jobs


# ---------------------------------------------------------------------------
# Ashby API
# ---------------------------------------------------------------------------

async def fetch_ashby_jobs(slug: str) -> list[dict]:
    """Fetch all jobs from an Ashby job board API.

    API: GET https://api.ashbyhq.com/posting-api/job-board/{slug}
    Returns the full board with jobs and descriptions.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=ATS_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            jobs_raw = data.get("jobs", [])
        except Exception as e:
            logger.error(f"Ashby API error for {slug}: {e}")
            return []

    jobs = []
    for job in jobs_raw:
        # Ashby provides location as a string and sometimes a locationName
        location = job.get("location", "")
        if not location:
            location = job.get("locationName", "")

        # Department/team
        department = job.get("departmentName", "") or job.get("department", "")

        # Description — Ashby includes descriptionHtml or descriptionPlain
        raw_jd = ""
        if job.get("descriptionHtml"):
            raw_jd = _strip_html_tags(job["descriptionHtml"])
        elif job.get("descriptionPlain"):
            raw_jd = job["descriptionPlain"]

        # Posting URL
        posting_url = job.get("jobUrl", "") or job.get("applicationUrl", "")

        jobs.append({
            "title": job.get("title", ""),
            "url": posting_url,
            "location": location,
            "department": department,
            "raw_jd": raw_jd,
        })

    logger.info(f"Ashby [{slug}]: fetched {len(jobs)} jobs")
    return jobs


# ---------------------------------------------------------------------------
# Lever API
# ---------------------------------------------------------------------------

async def fetch_lever_jobs(slug: str) -> list[dict]:
    """Fetch all jobs from a Lever postings API.

    API: GET https://api.lever.co/v0/postings/{slug}
    Returns an array of posting objects with descriptions.
    """
    url = f"https://api.lever.co/v0/postings/{slug}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=ATS_TIMEOUT)
            response.raise_for_status()
            jobs_raw = response.json()
        except Exception as e:
            logger.error(f"Lever API error for {slug}: {e}")
            return []

    if not isinstance(jobs_raw, list):
        logger.error(f"Lever [{slug}]: unexpected response format")
        return []

    jobs = []
    for job in jobs_raw:
        # Location from categories
        location = ""
        categories = job.get("categories", {})
        if categories.get("location"):
            location = categories["location"]

        # Department/team
        department = categories.get("team", "") or categories.get("department", "")

        # Description — Lever provides descriptionPlain
        raw_jd = job.get("descriptionPlain", "")

        # Also include the lists (requirements, responsibilities etc)
        lists = job.get("lists", [])
        for lst in lists:
            list_text = lst.get("text", "")
            list_content = lst.get("content", "")
            if list_text:
                raw_jd += f"\n\n{list_text}\n"
            if list_content:
                raw_jd += _strip_html_tags(list_content)

        posting_url = job.get("hostedUrl", "") or job.get("applyUrl", "")

        jobs.append({
            "title": job.get("text", ""),
            "url": posting_url,
            "location": location,
            "department": department,
            "raw_jd": raw_jd.strip(),
        })

    logger.info(f"Lever [{slug}]: fetched {len(jobs)} jobs")
    return jobs


# ---------------------------------------------------------------------------
# Amazon (amazon.jobs structured search API)
# ---------------------------------------------------------------------------
# Amazon runs a proprietary board with a public JSON search endpoint that
# returns structured location + org (business_category) data — far better
# than scraping Brave snippets. Sam's Amazon focus is narrow:
#   • AWS + AGI orgs only (business_category aws / amazon-artificial-...)
#   • Seattle only
#   • Product Manager roles
# The endpoint's location facet doesn't filter strictly, so we post-filter
# on normalized_location. Sorted by recency; capped per run to bound the
# number of inline scoring calls (dedup surfaces the rest on later runs).

AMAZON_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
AMAZON_TARGET_BUSINESS_CATEGORIES = [
    "aws",
    "amazon-artificial-general-intelligence",
]
AMAZON_TARGET_CITY = "seattle"
AMAZON_RESULT_CAP = 30


async def fetch_amazon_jobs(slug: str = "amazon") -> list[dict]:
    """Fetch Seattle AWS/AGI Product Manager roles from amazon.jobs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json",
    }
    base_params = [("business_category[]", c) for c in AMAZON_TARGET_BUSINESS_CATEGORIES]
    base_params += [("base_query", "Product Manager"), ("sort", "recent")]

    jobs: list[dict] = []
    seen: set[str] = set()
    offset, page_size = 0, 100

    async with httpx.AsyncClient() as client:
        for _ in range(5):  # safeguard against runaway pagination
            params = base_params + [
                ("result_limit", str(page_size)),
                ("offset", str(offset)),
            ]
            try:
                resp = await client.get(
                    AMAZON_SEARCH_URL, params=params, headers=headers, timeout=ATS_TIMEOUT
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Amazon jobs API error (offset={offset}): {e}")
                break

            page = data.get("jobs", [])
            if not page:
                break

            for j in page:
                location = j.get("normalized_location") or ""
                if AMAZON_TARGET_CITY not in location.lower():
                    continue
                path = j.get("job_path") or ""
                if not path:
                    continue
                posting_url = f"https://www.amazon.jobs{path}"
                if posting_url in seen:
                    continue
                seen.add(posting_url)

                raw = j.get("description") or j.get("description_short") or ""
                # Amazon truncates "Manager" → "Mgr" in many titles, which
                # breaks the spelled-out "product manager" keyword match.
                # Normalize for both matching and clean display.
                title = re.sub(r"\bMgr\b", "Manager", j.get("title", ""))
                jobs.append({
                    "title": title,
                    "url": posting_url,
                    "location": location,
                    "department": j.get("business_category", ""),
                    "raw_jd": _strip_html_tags(raw) if raw else "",
                })
                if len(jobs) >= AMAZON_RESULT_CAP:
                    break

            if len(jobs) >= AMAZON_RESULT_CAP:
                break

            total = data.get("hits", 0)
            offset += page_size
            if offset >= total:
                break

    logger.info(
        f"Amazon [{slug}]: fetched {len(jobs)} Seattle AWS/AGI jobs "
        f"(cap {AMAZON_RESULT_CAP})"
    )
    return jobs


# ---------------------------------------------------------------------------
# Unified fetcher
# ---------------------------------------------------------------------------

async def fetch_jobs_from_ats(platform: str, slug: str) -> list[dict]:
    """Fetch jobs from the appropriate ATS API based on platform."""
    if platform == "greenhouse":
        return await fetch_greenhouse_jobs(slug)
    elif platform == "ashby":
        return await fetch_ashby_jobs(slug)
    elif platform == "lever":
        return await fetch_lever_jobs(slug)
    elif platform == "amazon":
        return await fetch_amazon_jobs(slug)
    else:
        logger.warning(f"Unknown ATS platform: {platform}")
        return []


def filter_jobs_for_profile(jobs: list[dict]) -> list[dict]:
    """Filter ATS jobs by US location and relevant role keywords.

    Returns only jobs that are:
    1. Based in the US (or Remote)
    2. Have a title matching Sam's target role types
    """
    filtered = []
    for job in jobs:
        if not _is_us_location(job["location"]):
            continue
        if not _matches_role_keywords(
            job["title"],
            job.get("raw_jd", ""),
            job.get("department", ""),
        ):
            continue
        filtered.append(job)

    return filtered
