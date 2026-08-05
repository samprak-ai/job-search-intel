"""JD scraping service — fetches actual job descriptions from role URLs.

Uses httpx to fetch page HTML and extracts text content.
Works well for Greenhouse, Lever, and static career pages.
LinkedIn and JS-heavy pages (Ashby) may not yield full JDs.
"""

import logging
import re
from html import unescape

import httpx

from app.config import get_supabase_client
from app.services.jd_quality import is_substantive_jd

logger = logging.getLogger(__name__)

# Threshold: if existing JD is shorter than this, attempt scraping
MIN_JD_LENGTH = 80

# Placeholder texts that indicate a missing JD
PLACEHOLDER_TEXTS = [
    "we cannot provide a description",
    "you need to enable javascript",
    "enable javascript to run this app",
]


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities to get plain text."""
    # Remove script and style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "\n", text)
    # Decode HTML entities
    text = unescape(text)
    # Collapse whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_jd_from_html(html: str, source: str) -> str | None:
    """Extract the job description from page HTML based on source type."""

    # Greenhouse: look for the content div
    if source == "greenhouse":
        match = re.search(
            r'<div\s+id="content"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            html, re.DOTALL
        )
        if not match:
            # Broader match
            match = re.search(
                r'class="job-post[^"]*"[^>]*>(.*?)<div\s+id="application"',
                html, re.DOTALL
            )
        if match:
            return _strip_html(match.group(1))

    # Lever: look for the posting content
    if source == "lever":
        match = re.search(
            r'<div\s+class="section-wrapper[^"]*">(.*?)<div\s+class="section.*?Apply',
            html, re.DOTALL
        )
        if match:
            return _strip_html(match.group(1))

    # Google Careers: the detail page carries "About the job" + "Responsibilities".
    # The search-RESULTS CARD does not — parsing a card is what produced 122
    # bodyless JDs (L28). Anchor on the detail-page sections so a card can never
    # masquerade as a JD.
    if source == "google_careers":
        match = re.search(
            r"(About the job.*?)(?:</main>|Learn more share link|share link Copy link)",
            html, re.DOTALL | re.IGNORECASE,
        )
        if match:
            text = _strip_html(match.group(1))
            if is_substantive_jd(text):
                return text
        return None  # never fall through to the generic path for Google

    # Generic: try to extract main content area
    # Look for common job description containers
    patterns = [
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*job[-_]?desc[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*posting[-_]?desc[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]*class="[^"]*content[-_]?body[^"]*"[^>]*>(.*?)</div>',
        r'<main[^>]*>(.*?)</main>',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if match:
            text = _strip_html(match.group(1))
            if len(text) > 200:  # Only use if we got substantial content
                return text

    # Last resort: strip the full page
    full_text = _strip_html(html)
    if len(full_text) > 300:
        return full_text[:5000]  # Cap at 5000 chars

    return None


def _needs_jd_update(raw_jd: str | None) -> bool:
    """Check if a role's JD is missing, a placeholder, or not substantive.

    Length alone is NOT a sufficient test (L28). Google Careers cards run
    565-1200 chars — comfortably over MIN_JD_LENGTH — yet contain only the
    title, location and Minimum-qualifications snippet, with no responsibilities
    body. Under the old length-only rule these roles were never re-enriched,
    and 49 of them carried a Strong/Perfect score derived from a card.
    Delegate the real decision to is_substantive_jd().
    """
    if not raw_jd or len(raw_jd) < MIN_JD_LENGTH:
        return True
    lower = raw_jd.lower()
    if any(p in lower for p in PLACEHOLDER_TEXTS):
        return True
    return not is_substantive_jd(raw_jd)


async def scrape_jd(url: str, source: str) -> str | None:
    """Fetch a URL and extract the job description text.

    Returns the extracted JD text, or None if scraping failed.
    """
    # Skip LinkedIn — they block scraping
    if "linkedin.com" in url:
        logger.debug(f"Skipping LinkedIn URL (blocked): {url}")
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()

            html = response.text
            if len(html) < 100:
                return None

            jd_text = _extract_jd_from_html(html, source)

            # Substance, not length (L28): a 6,293-char LinkedIn scrape of
            # benefits + Fair Chance ordinance text passes a length test and
            # contains no job content. Never persist text we can't verify.
            if jd_text and is_substantive_jd(jd_text):
                logger.info(f"Scraped JD ({len(jd_text)} chars) from {url}")
                return jd_text
            else:
                logger.debug(f"Could not extract a substantive JD from {url}")
                return None

    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP {e.response.status_code} fetching {url}")
        return None
    except Exception as e:
        logger.warning(f"Failed to scrape {url}: {e}")
        return None


async def enrich_missing_jds() -> dict:
    """Find all roles with missing/placeholder JDs and attempt to scrape them.

    Returns a summary of enrichment results.
    """
    supabase = get_supabase_client()

    # Fetch all roles
    result = supabase.table("roles").select("id, url, source, raw_jd").execute()
    all_roles = result.data

    candidates = [r for r in all_roles if _needs_jd_update(r.get("raw_jd"))]
    logger.info(f"Found {len(candidates)} roles needing JD enrichment out of {len(all_roles)} total")

    enriched = 0
    skipped = 0
    failed = 0

    for role in candidates:
        jd = await scrape_jd(role["url"], role["source"])

        if jd:
            supabase.table("roles").update({"raw_jd": jd}).eq("id", role["id"]).execute()
            enriched += 1
        elif "linkedin.com" in role["url"]:
            skipped += 1
        else:
            failed += 1

    return {
        "total_scanned": len(all_roles),
        "candidates": len(candidates),
        "enriched": enriched,
        "skipped_linkedin": skipped,
        "failed": failed,
    }
