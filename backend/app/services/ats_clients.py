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
    "north america",
]

# Role title keywords that match Sam's target profile.
# Tuned to his 5 target role types: AI Solutions Engineer, AI Partnerships,
# Head of AI Product, GTM Strategy AI, Sales Intelligence AI.
# Uses compound terms to avoid matching generic "engineer" or "product" roles.
ROLE_KEYWORDS = [
    # Solutions / Applied AI roles
    "solutions architect", "solutions engineer", "applied ai",
    "forward deployed", "customer engineer", "customer success",
    "technical deployment", "evangelist",
    # Partnerships & BD
    "partner", "partnerships", "business development",
    # GTM / Strategy
    "gtm", "go-to-market", "go to market",
    # Product roles (scoped — "product manager", "product lead", "product marketing")
    "product manager", "product lead", "product marketing",
    "product owner", "product management",
    # Sales roles
    "account executive", "sales engineer", "sales intelligence",
    "sales architect",
    # Strategy & Ops
    "strategy & operations", "strategic account",
    "strategic growth",
    # Head / Director level
    "head of",
]

# Titles to explicitly EXCLUDE even if keywords match
ROLE_EXCLUDE_KEYWORDS = [
    "software engineer", "research engineer", "ml engineer",
    "machine learning engineer", "infrastructure engineer",
    "data engineer", "design engineer", "ui engineer",
    "video", "recruiter", "recruiting", "counsel",
    "accounting", "accountant", "finance &",
    "supply chain", "security fellow", "safety fellow",
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
    return any(kw in lower for kw in US_LOCATION_KEYWORDS)


def _matches_role_keywords(title: str) -> bool:
    """Check if a job title matches Sam's target role types.

    Must match at least one ROLE_KEYWORD and not match any ROLE_EXCLUDE_KEYWORDS.
    """
    lower = title.lower()
    if any(ex in lower for ex in ROLE_EXCLUDE_KEYWORDS):
        return False
    return any(kw in lower for kw in ROLE_KEYWORDS)


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
        if not _matches_role_keywords(job["title"]):
            continue
        filtered.append(job)

    return filtered
