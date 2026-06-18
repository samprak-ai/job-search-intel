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

import asyncio
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
    # GTM systems builder roles + GTM specialist (AWS WWSO-style GTM roles)
    "gtm systems", "gtm automation", "go-to-market systems",
    "go to market systems", "sales intelligence",
    "business systems", "ai operations", "systems and ai",
    "partner business systems",
    "gtm specialist", "go-to-market specialist", "gtm lead",
    "go-to-market lead", "gtm strategy", "go-to-market strategy",
    "strategy and operations", "strategy & operations",
    "business operations and strategy", "sales strategy", "revenue strategy",
    # Business strategy / business operations (Sam's S&O / business-strategy targets;
    # caught real misses like Google "Business Strategy and GTM Partner Operations
    # Lead" and OpenAI "GTM Business Operations & Strategy Lead"). & is normalized
    # to "and" in _matches_role_keywords so "Ops & Strategy" == "Ops and Strategy".
    "business strategy", "business operations", "gtm operations",
    # AI / GTM / startup / strategic partnerships — "AI Partnerships" is an explicit
    # target_role_type. Kept specific (not bare "partnership") to avoid pulling in
    # channel/SI/event/federal sales-partnership roles. Caught real misses like
    # Anthropic "Amazon GTM Partnership, Startups" and "Startup Partnerships Lead".
    "ai partnership", "gtm partnership", "strategic partnership",
    "startup partnership", "frontier partnership", "platform partnership",
    # Partner / specialist / strategist families (from Sam's saved-roles signal, L13a):
    # WWSO GenAI / Data & AI GTM Specialist, Partner Specialist, Partner Development
    # Manager, GenAI Strategist, Deal Intelligence PMT. These are his real Amazon targets.
    "partner specialist", "worldwide specialist", "ww specialist",
    "partner development manager", "partner development",
    "genai strategist", "ai strategist", "deal intelligence",
    "frontier ai partner",
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
    # Normalize "&" → "and" so "Business Operations & Strategy" matches the
    # "...and strategy" / "business operations" keywords (real Google/OpenAI misses).
    lower = title.lower().replace(" & ", " and ")
    if any(ex in lower for ex in ROLE_EXCLUDE_KEYWORDS):
        return False
    if not any(kw in lower for kw in ROLE_KEYWORDS):
        return False

    context = f"{title} {department} {raw_jd[:3000]}".lower().replace(" & ", " and ")
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

        # Build the posting URL. Some boards embed Greenhouse on their own domain
        # and carry the job id in the QUERY string (e.g. Databricks:
        # databricks.com/.../job?gh_jid=123). Our discovery URL-normalizer strips
        # the query, which would collapse every such posting to one identical path
        # — only one survives dedup and the stored "View Original" link is a dead
        # generic careers page. Fall back to the canonical Greenhouse-hosted URL
        # (id in the path) whenever the absolute_url doesn't already carry it. (L22)
        posting_url = job.get("absolute_url", "") or ""
        job_id = job.get("id")
        if job_id and f"/jobs/{job_id}" not in posting_url:
            posting_url = f"https://job-boards.greenhouse.io/{slug}/jobs/{job_id}"

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
# than scraping Brave snippets. Sam's Amazon focus:
#   • AWS + AGI orgs only (business_category aws / amazon-artificial-...)
#   • Seattle (incl. roles where Seattle is one of several posted locations)
#   • Product Manager AND GTM Specialist roles (both are Sam target types)
# The endpoint's location facet doesn't filter strictly, so we post-filter
# on the job's full locations list. Sorted by recency; capped per run to
# bound inline scoring calls (dedup surfaces the rest on later runs).

AMAZON_SEARCH_URL = "https://www.amazon.jobs/en/search.json"
AMAZON_TARGET_BUSINESS_CATEGORIES = [
    "aws",
    "amazon-artificial-general-intelligence",
]
# One search pass per query phrase. Amazon's base_query is a relevance search,
# so a "GTM Specialist" role won't surface under "Product Manager" — each
# target role family needs its own pass.
AMAZON_BASE_QUERIES = [
    "Product Manager", "GTM Specialist",
    # Added from Sam's saved-roles signal (L13a): his real Amazon targets cluster in
    # the Partner/Specialist/Strategist families, which the first two passes miss.
    "Partner Specialist", "Worldwide Specialist", "Partner Development Manager",
    "GenAI Strategist", "Deal Intelligence",
]
AMAZON_TARGET_CITY = "seattle"
# Per-query cap so each role family gets fair representation — otherwise the
# first (high-volume) query exhausts the budget before the next one runs.
AMAZON_RESULT_CAP_PER_QUERY = 20

# Principal (L7) and above is a level up from Sam's band. Internal transfers
# rarely clear a level jump, so Principal/Sr Principal/Director roles aren't
# realistic targets — exclude them at the source so they never reach scoring or
# the match list (internal-transfer scoring would otherwise inflate them to
# Perfect/Strong). Word-boundary match; "Principal" is never abbreviated in
# Amazon titles. (L20 guard.)
AMAZON_LEVEL_UP_RE = re.compile(r"\b(principal|director|vice president|\bvp\b)\b", re.IGNORECASE)


def _amazon_job_in_target_city(job: dict) -> bool:
    """True if the target city is the primary OR any listed location.

    Many Amazon roles post to several cities (e.g. SF / Austin / Seattle) with
    a non-Seattle primary `normalized_location`. The full `locations` list (a
    list of JSON-string blobs) is the source of truth — a substring check on it
    is enough to tell whether Seattle is one of the options.
    """
    if AMAZON_TARGET_CITY in (job.get("normalized_location") or "").lower():
        return True
    for loc in job.get("locations") or []:
        if AMAZON_TARGET_CITY in str(loc).lower():
            return True
    return False


async def fetch_amazon_jobs(slug: str = "amazon") -> list[dict]:
    """Fetch Seattle AWS/AGI Product Manager + GTM roles from amazon.jobs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json",
    }
    category_params = [("business_category[]", c) for c in AMAZON_TARGET_BUSINESS_CATEGORIES]

    jobs: list[dict] = []
    seen: set[str] = set()

    async with httpx.AsyncClient() as client:
        for base_query in AMAZON_BASE_QUERIES:
            kept_this_query = 0
            offset, page_size = 0, 100
            for _ in range(5):  # safeguard against runaway pagination
                params = category_params + [
                    ("base_query", base_query),
                    ("sort", "recent"),
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
                    logger.error(f"Amazon jobs API error (q={base_query!r}, offset={offset}): {e}")
                    break

                page = data.get("jobs", [])
                if not page:
                    break

                for j in page:
                    if not _amazon_job_in_target_city(j):
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
                    # Skip level-up roles (Principal+) — not realistic internal moves.
                    if AMAZON_LEVEL_UP_RE.search(title):
                        continue
                    jobs.append({
                        "title": title,
                        "url": posting_url,
                        "location": j.get("normalized_location") or "",
                        "department": j.get("business_category", ""),
                        "raw_jd": _strip_html_tags(raw) if raw else "",
                    })
                    kept_this_query += 1
                    if kept_this_query >= AMAZON_RESULT_CAP_PER_QUERY:
                        break

                if kept_this_query >= AMAZON_RESULT_CAP_PER_QUERY:
                    break
                total = data.get("hits", 0)
                offset += page_size
                if offset >= total:
                    break

    logger.info(
        f"Amazon [{slug}]: fetched {len(jobs)} Seattle AWS/AGI PM+GTM jobs "
        f"({AMAZON_RESULT_CAP_PER_QUERY}/query)"
    )
    return jobs


# ---------------------------------------------------------------------------
# Google Careers (server-rendered search — the individual job pages are SPAs,
# but jobs/results/?q=... renders the result cards in HTML, with title +
# location + a qualifications snippet). This is the reliable way to enumerate
# Google roles (Brave's index is stale/partial; the careers backend API 404s).
# ---------------------------------------------------------------------------

GOOGLE_CAREERS_SEARCH_URL = "https://www.google.com/about/careers/applications/jobs/results/"
GOOGLE_CAREERS_QUERIES = [
    "AI strategy operations",
    "strategy and operations",
    "go-to-market strategy",
    "AI product manager",
    "product strategy growth",
    "chief of staff",
    "applied AI",
]
GOOGLE_CAREERS_PAGES = 2  # 20 results/page
_GC_ACRONYMS = {"ai": "AI", "gtm": "GTM", "ml": "ML", "ai/ml": "AI/ML", "api": "API",
                "ux": "UX", "ar": "AR", "vr": "VR", "llm": "LLM", "genai": "GenAI", "us": "US"}
_GC_LOWER = {"and", "of", "the", "for", "to", "in", "on", "a", "an", "&"}


def _gc_deslug(slug: str) -> str:
    words = []
    for i, w in enumerate(slug.split("-")):
        if w in _GC_ACRONYMS:
            words.append(_GC_ACRONYMS[w])
        elif w in _GC_LOWER and i != 0:
            words.append(w)
        else:
            words.append(w.capitalize())
    return " ".join(words)


def _parse_google_careers(html_text: str) -> list[dict]:
    """Extract job cards from a results page.

    Each posting is one `<li ... lLd3Je ...>` card — split on that so card
    boundaries are correct. (The job link repeats within a card as href +
    aria-label + share link, so naive between-matches segmentation leaked the
    NEXT card's location/JD into this one — which mis-scored a Singapore/Mumbai
    role as US.) Location default is empty (NOT "United States"), so a role whose
    location can't be parsed gets filtered by the US check rather than passed.
    """
    out: dict[str, dict] = {}
    cards = re.split(r"<li[^>]*\blLd3Je\b", html_text)[1:]
    for card in cards:
        m = re.search(r"jobs/results/(\d+)-([a-z0-9-]+)", card)
        if not m:
            continue
        job_id, slug = m.group(1), m.group(2)
        if job_id in out:
            continue
        am = re.search(r'aria-label="Learn more about ([^"]+)"', card)
        title = unescape(am.group(1)).strip() if am else _gc_deslug(slug)

        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", card[:5000]))).strip()
        # Location follows the "place" icon label, up to share/qualification text.
        loc_m = re.search(
            r"\bplace\s+(.+?)(?:\s+(?:share|bookmark|bar_chart|corporate_fare|Minimum|Learn more|Apply)\b|$)",
            text,
        )
        location = re.sub(r"\s*;\s*", "; ", loc_m.group(1).strip()) if loc_m else ""

        out[job_id] = {
            "title": title,
            "url": f"https://www.google.com/about/careers/applications/jobs/results/{job_id}-{slug}/",
            "location": location,
            "department": "",
            "raw_jd": text[:1500],
        }
    return list(out.values())


async def fetch_google_careers_jobs(slug: str = "google") -> list[dict]:
    """Enumerate Google Careers roles across Sam's target keyword queries."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    jobs: dict[str, dict] = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in GOOGLE_CAREERS_QUERIES:
            for page in range(1, GOOGLE_CAREERS_PAGES + 1):
                try:
                    resp = await client.get(
                        GOOGLE_CAREERS_SEARCH_URL,
                        params={"q": query, "page": page},
                        headers=headers, timeout=ATS_TIMEOUT,
                    )
                    if resp.status_code != 200:
                        break
                except Exception as e:
                    logger.warning(f"Google Careers search failed ('{query}' p{page}): {e}")
                    break
                page_jobs = _parse_google_careers(resp.text)
                if not page_jobs:
                    break
                for j in page_jobs:
                    jobs.setdefault(j["url"], j)
                await asyncio.sleep(0.4)
    logger.info(f"Google Careers: fetched {len(jobs)} unique jobs across {len(GOOGLE_CAREERS_QUERIES)} queries")
    return list(jobs.values())


# ---------------------------------------------------------------------------
# LinkedIn (public guest job-search API — no login)
# ---------------------------------------------------------------------------
# Brave/Serper barely index LinkedIn job pages, so LinkedIn-posted roles get
# missed. LinkedIn exposes a public guest endpoint that SEARCHES jobs by company
# id (f_C) + keywords and returns HTML job cards, plus a per-job endpoint for the
# description — no auth. This is a supplementary source for companies that carry
# a linkedin_company_id in companies.json (e.g. Google = 1441).

LINKEDIN_GUEST_SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)
LINKEDIN_GUEST_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"

# Keyword passes aligned to Sam's target role types (incl. Strategy & Ops, which
# Google posts heavily and the PM/AI-only queries were missing). LinkedIn
# rate-limits a burst hard, so we take only a few per query and cycle through
# all of them first (diversity over depth) — leading with Sam's distinctive
# targets so they land before any block.
LINKEDIN_QUERIES = [
    "strategy and operations",
    "go-to-market strategy",
    "AI product manager",
    "chief of staff",
    "product strategy growth",
]
LINKEDIN_CAP_PER_QUERY = 6
LINKEDIN_CAP_PER_COMPANY = 25


def _linkedin_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    }


def _clean_card_text(m) -> str:
    return unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""


def _parse_linkedin_cards(html: str) -> list[dict]:
    """Parse guest-search HTML into {id, title, location, url} cards."""
    out = []
    for li in re.findall(r"<li>(.*?)</li>", html, re.S):
        link = re.search(r'href="(https://www\.linkedin\.com/jobs/view/[^?"]+)', li)
        if not link:
            continue
        jid = re.search(r"-(\d+)(?:/|$)", link.group(1))
        if not jid:
            continue
        job_id = jid.group(1)
        title = _clean_card_text(
            re.search(r"(?:base-search-card__title|job-search-card__title)[^>]*>(.*?)</", li, re.S)
        )
        loc = _clean_card_text(
            re.search(r"job-search-card__location[^>]*>(.*?)</", li, re.S)
        )
        if not title:
            continue
        out.append({
            "id": job_id,
            "title": title,
            "location": loc,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        })
    return out


async def _fetch_linkedin_jd(client: httpx.AsyncClient, job_id: str) -> str:
    """Fetch a single LinkedIn job's description text (best-effort)."""
    try:
        resp = await client.get(
            LINKEDIN_GUEST_JOB_URL.format(id=job_id),
            headers=_linkedin_headers(),
            timeout=ATS_TIMEOUT,
        )
        if resp.status_code != 200:
            return ""
        m = re.search(r'(?:show-more-less-html__markup|description__text)[^>]*>(.*?)</div>', resp.text, re.S)
        return _strip_html_tags(m.group(1)) if m else ""
    except Exception:
        return ""


async def fetch_linkedin_jobs(company_id: str, company_name: str) -> list[dict]:
    """Search LinkedIn (guest) for a company's roles across Sam's keyword passes."""
    jobs: list[dict] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for query in LINKEDIN_QUERIES:
            if len(jobs) >= LINKEDIN_CAP_PER_COMPANY:
                break
            params = {
                "f_C": company_id,
                "keywords": query,
                "location": "United States",
                "start": 0,
            }
            try:
                resp = await client.get(
                    LINKEDIN_GUEST_SEARCH_URL, params=params,
                    headers=_linkedin_headers(), timeout=ATS_TIMEOUT,
                )
                if resp.status_code != 200:
                    logger.info(f"LinkedIn [{company_name}] '{query}' -> {resp.status_code} (rate-limited); stopping")
                    break
                cards = _parse_linkedin_cards(resp.text)
            except Exception as e:
                logger.warning(f"LinkedIn search failed ({company_name}, '{query}'): {e}")
                break
            kept = 0
            for c in cards:
                if c["url"] in seen:
                    continue
                seen.add(c["url"])
                c_jd = await _fetch_linkedin_jd(client, c["id"])
                jobs.append({
                    "title": c["title"],
                    "url": c["url"],
                    "location": c["location"],
                    "department": "",
                    "raw_jd": c_jd,
                })
                kept += 1
                if kept >= LINKEDIN_CAP_PER_QUERY or len(jobs) >= LINKEDIN_CAP_PER_COMPANY:
                    break
            await asyncio.sleep(1.0)  # be gentle with LinkedIn between queries
    logger.info(f"LinkedIn [{company_name}]: fetched {len(jobs)} jobs (cap {LINKEDIN_CAP_PER_COMPANY})")
    return jobs


# ---------------------------------------------------------------------------
# Workday API (CXS — Candidate Experience Service, public, no auth)
# ---------------------------------------------------------------------------
#
# Workday boards expose a stable JSON API at:
#   POST https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
#   body: {"appliedFacets":{}, "limit":20, "offset":0, "searchText": "<q>"}
#   -> {"total": int, "jobPostings": [{title, externalPath, locationsText, postedOn, ...}]}
# Per-job description:
#   GET  https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}
#   -> {"jobPostingInfo": {"jobDescription": "<html>", ...}}
# Public apply URL:
#   https://{host}.myworkdayjobs.com/{site}{externalPath}
#
# Coordinates per company are kept in WORKDAY_BOARDS keyed by ats_slug so the
# unified (platform, slug) dispatcher signature stays unchanged. Add a company
# by appending one entry here and setting ats_platform="workday" + ats_slug.

# host is the subdomain before ".myworkdayjobs.com" (includes the wdN cell).
WORKDAY_BOARDS = {
    "nvidia": {
        "host": "nvidia.wd5",
        "tenant": "nvidia",
        "site": "NVIDIAExternalCareerSite",
    },
}

# Keyword queries run through Workday's searchText (one pass each, deduped by
# externalPath). Mirrors the per-family approach used for Amazon/Google.
WORKDAY_QUERIES = [
    "product manager", "product strategy", "ai product",
    "go to market", "gtm", "strategy and operations", "chief of staff",
]

WORKDAY_LIMIT = 20          # page size per CXS request
WORKDAY_MAX_PAGES = 5       # cap pages per query (<=100 postings/query)
WORKDAY_DETAIL_CAP = 60     # cap per-job JD detail fetches per company/run
_WORKDAY_HEADERS = {
    # Workday returns 403 to non-browser-ish clients on some tenants.
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


async def _fetch_workday_jd(
    client: httpx.AsyncClient, host: str, tenant: str, site: str, external_path: str
) -> str:
    """Fetch and strip a single Workday job description. Best-effort."""
    url = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{external_path}"
    try:
        resp = await client.get(url, headers=_WORKDAY_HEADERS, timeout=ATS_TIMEOUT)
        resp.raise_for_status()
        info = resp.json().get("jobPostingInfo", {})
        return _strip_html_tags(info.get("jobDescription", "") or "")
    except Exception as e:
        logger.warning(f"Workday JD fetch failed ({tenant}{external_path}): {e}")
        return ""


async def fetch_workday_jobs(slug: str) -> list[dict]:
    """Fetch jobs from a Workday CXS board, normalized to the common format.

    JD detail requires a second request per posting, so we pre-filter by title
    and US location BEFORE fetching descriptions to keep the request count
    bounded (WORKDAY_DETAIL_CAP).
    """
    board = WORKDAY_BOARDS.get(slug)
    if not board:
        logger.error(f"Workday: no board config for slug '{slug}' (add to WORKDAY_BOARDS)")
        return []
    host, tenant, site = board["host"], board["tenant"], board["site"]
    jobs_base = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

    seen_paths: set[str] = set()
    candidates: list[dict] = []  # postings that pass title+location pre-filter

    async with httpx.AsyncClient() as client:
        for query in WORKDAY_QUERIES:
            for page in range(WORKDAY_MAX_PAGES):
                body = {
                    "appliedFacets": {},
                    "limit": WORKDAY_LIMIT,
                    "offset": page * WORKDAY_LIMIT,
                    "searchText": query,
                }
                try:
                    resp = await client.post(
                        jobs_base, json=body, headers=_WORKDAY_HEADERS, timeout=ATS_TIMEOUT
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    logger.warning(f"Workday [{tenant}] '{query}' p{page} error: {e}")
                    break

                postings = data.get("jobPostings", [])
                if not postings:
                    break

                for p in postings:
                    path = p.get("externalPath", "")
                    if not path or path in seen_paths:
                        continue
                    seen_paths.add(path)
                    title = p.get("title", "")
                    location = p.get("locationsText", "")
                    # Pre-filter before paying for the JD detail request.
                    if not _is_us_location(location):
                        continue
                    if not _matches_role_keywords(title):
                        continue
                    candidates.append(
                        {"title": title, "location": location, "externalPath": path}
                    )

                total = data.get("total", 0)
                if (page + 1) * WORKDAY_LIMIT >= total:
                    break

        # Fetch JD detail for the bounded candidate set.
        jobs: list[dict] = []
        for c in candidates[:WORKDAY_DETAIL_CAP]:
            raw_jd = await _fetch_workday_jd(client, host, tenant, site, c["externalPath"])
            jobs.append({
                "title": c["title"],
                "url": f"https://{host}.myworkdayjobs.com/{site}{c['externalPath']}",
                "location": c["location"],
                "department": "",
                "raw_jd": raw_jd,
            })

    logger.info(
        f"Workday [{tenant}]: {len(seen_paths)} unique postings scanned, "
        f"{len(jobs)} matched + detailed"
    )
    return jobs


# ---------------------------------------------------------------------------
# Unified fetcher
# ---------------------------------------------------------------------------

async def fetch_jobs_from_ats(platform: str, slug: str) -> list[dict]:
    """Fetch jobs from the appropriate ATS API based on platform."""
    if platform == "greenhouse":
        return await fetch_greenhouse_jobs(slug)
    elif platform == "workday":
        return await fetch_workday_jobs(slug)
    elif platform == "ashby":
        return await fetch_ashby_jobs(slug)
    elif platform == "lever":
        return await fetch_lever_jobs(slug)
    elif platform == "amazon":
        return await fetch_amazon_jobs(slug)
    elif platform == "google_careers":
        return await fetch_google_careers_jobs(slug)
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
