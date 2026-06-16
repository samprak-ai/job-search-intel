import asyncio
import logging

from fastapi import APIRouter, HTTPException, Header
from typing import Annotated

from app.config import get_settings, get_supabase_client, load_companies
from app.services.discovery import discover_all, discover_for_company, cleanup_junk_roles, wipe_all_roles, backfill_departments
from app.services.role_discovery import discover_by_role
from app.services.jd_scraper import enrich_missing_jds

logger = logging.getLogger(__name__)
router = APIRouter()

# Bounded daily-cron default when CRON_COMPANIES is unset. Keep in sync with the
# "Daily cron scope" section of CLAUDE.md (guarded by selfcheck L5).
DEFAULT_CRON_COMPANIES = ["Anthropic", "OpenAI", "Amazon", "Google DeepMind", "Google", "Databricks", "NVIDIA", "Snowflake"]


async def _auto_score_unscored() -> tuple[int, int]:
    """Score all unscored roles. Returns (scored_count, failed_count)."""
    from app.services.scoring import score_role as score_fn

    supabase = get_supabase_client()
    scored_result = supabase.table("role_scores").select("role_id").execute()
    scored_ids = {r["role_id"] for r in scored_result.data}

    roles_result = supabase.table("roles").select("id, title, company").execute()
    unscored = [r for r in roles_result.data if r["id"] not in scored_ids]

    scored_count = 0
    score_failed = 0
    for role in unscored:
        try:
            await score_fn(role["id"])
            scored_count += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            score_failed += 1
            logger.warning(f"Auto-score failed for {role['title']}: {e}")

    return scored_count, score_failed


@router.post("")
async def discover_roles():
    """Trigger role discovery across all target companies.

    Runs Brave Search queries for each company sequentially,
    deduplicates results, and stores new roles to the roles table.
    """
    try:
        results = await discover_all()
        total_new = sum(r["new_roles"] for r in results)

        # Auto-score any unscored roles
        scored_count = 0
        score_failed = 0
        if total_new > 0:
            scored_count, score_failed = await _auto_score_unscored()

        return {
            "status": "completed",
            "companies_searched": len(results),
            "total_new_roles": total_new,
            "auto_scored": scored_count,
            "score_failed": score_failed,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/wipe")
async def wipe_roles():
    """Delete ALL roles, scores, and sessions for a fresh start.

    WARNING: This is destructive. Use before a full re-discovery.
    """
    try:
        result = await wipe_all_roles()
        return {"status": "wiped", **result}
    except Exception as e:
        logger.error(f"Wipe failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cleanup")
async def cleanup_roles():
    """Remove junk entries from the roles table.

    Applies the same quality filters used during discovery to
    existing data, removing blog posts, guides, aggregation pages,
    and misattributed roles.
    """
    try:
        result = await cleanup_junk_roles()
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enrich")
async def enrich_jds():
    """Scrape missing job descriptions for existing roles.

    Finds roles with placeholder or missing JDs and attempts to
    fetch the actual content from the source URL. Skips LinkedIn
    (blocks scraping).
    """
    try:
        result = await enrich_missing_jds()
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"JD enrichment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backfill-departments")
async def backfill_departments_route():
    """Backfill department field for existing roles from ATS APIs.

    Re-fetches job data from each company's ATS and matches by URL
    to populate the department column. One-time operation.
    """
    try:
        result = await backfill_departments()
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Department backfill failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cron")
async def discover_cron(
    authorization: Annotated[str | None, Header()] = None,
):
    """Cron-triggered discovery for configured companies.

    Reads CRON_COMPANIES env var (comma-separated) for which companies to scan.
    Falls back to all companies if not set.
    After discovery, auto-scores any new unscored roles.

    Requires Bearer token matching CRON_SECRET for authentication.
    Designed to be called by Vercel Cron, Railway cron, or similar scheduler.
    """
    settings = get_settings()

    if not settings.cron_secret:
        raise HTTPException(
            status_code=500, detail="CRON_SECRET not configured"
        )

    expected = f"Bearer {settings.cron_secret}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        # Determine which companies to scan
        all_companies = load_companies()

        if settings.cron_companies.strip():
            cron_names = [
                name.strip()
                for name in settings.cron_companies.split(",")
                if name.strip()
            ]
            targets = [
                c for c in all_companies
                if c["name"] in cron_names
            ]
            if not targets:
                raise HTTPException(
                    status_code=400,
                    detail=f"None of CRON_COMPANIES matched: {cron_names}",
                )
        else:
            # No env override → scan the bounded default set, NOT all 27
            # (all-27 blows the ~15-min runtime budget). Keeps Amazon in scope
            # even if the Railway env var is cleared.
            targets = [c for c in all_companies if c["name"] in DEFAULT_CRON_COMPANIES]

        logger.info(
            f"Cron scanning {len(targets)} companies: {[c['name'] for c in targets]}"
        )

        # Run discovery for each target company
        results = []
        for company in targets:
            summary = await discover_for_company(company)
            results.append(summary)
            await asyncio.sleep(0.5)

        total_new = sum(r["new_roles"] for r in results)

        # Run role-based discovery only when explicitly enabled. This is the
        # expensive path because it searches broad title keywords every day.
        role_discovery_new = 0
        role_result = {"status": "skipped", "reason": "CRON_ENABLE_ROLE_DISCOVERY=false"}
        if settings.cron_enable_role_discovery:
            try:
                role_result = await discover_by_role()
                role_discovery_new = role_result.get("new_roles", 0)
                total_new += role_discovery_new
            except Exception as e:
                logger.warning(f"Role-based discovery failed: {e}")

        # Auto-score any unscored roles (not just new ones — catches retries)
        scored_count, score_failed = await _auto_score_unscored()

        # Run freshness checks on all existing roles
        stale_found = 0
        try:
            from app.services.freshness import check_all_freshness
            freshness_summary = await check_all_freshness()
            stale_found = freshness_summary.get("stale_found", 0)
        except Exception as e:
            logger.warning(f"Freshness check failed: {e}")

        # Send daily digest email
        try:
            from app.services.notifications import send_daily_digest_email

            await send_daily_digest_email(
                companies_searched=len(results),
                total_new=total_new,
                auto_scored=scored_count,
                score_failed=score_failed,
                stale_found=stale_found,
            )
        except Exception as e:
            logger.warning(f"Digest email failed: {e}")

        # Morning quick-apply packets (generate-only, bounded by quick_apply_max).
        # Folded into the daily cron so there is no separate Vercel cron.
        quick_apply_summary = None
        if settings.cron_enable_quick_apply:
            try:
                from app.services.quick_apply import run_quick_apply
                quick_apply_summary = run_quick_apply()
            except Exception as e:
                logger.warning(f"Quick-apply digest failed: {e}")

        return {
            "status": "completed",
            "trigger": "cron",
            "companies_searched": len(results),
            "company_names": [c["name"] for c in targets],
            "total_new_roles": total_new,
            "role_discovery_new": role_discovery_new,
            "role_discovery": role_result,
            "auto_scored": scored_count,
            "score_failed": score_failed,
            "stale_found": stale_found,
            "quick_apply": quick_apply_summary,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cron discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/by-role")
async def discover_roles_by_role():
    """Trigger role-based discovery across the open market.

    Searches for job title keywords (from profile target_role_types)
    across ATS platforms, not limited to the target company list.
    Discovers roles at companies we haven't pre-selected.
    """
    try:
        result = await discover_by_role()
        return result
    except Exception as e:
        logger.error(f"Role-based discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deep-scan")
async def deep_scan(
    authorization: Annotated[str | None, Header()] = None,
):
    """Weekly deep freshness scan with mandatory purge.

    Differs from /cron's daily freshness:
    - Force-rechecks every role (clears ATS listing cache)
    - Deletes is_live=False roles AND their scores after the scan
    - Returns per-company stale breakdown

    Requires Bearer token matching CRON_SECRET. Designed to be called
    by Vercel cron weekly (Sunday 14:00 UTC) but can be triggered
    manually for ad-hoc deep cleanups.
    """
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")

    expected = f"Bearer {settings.cron_secret}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        from app.services.freshness import deep_scan_freshness
        summary = await deep_scan_freshness(delete_stale=True)
        return {"status": "completed", "trigger": "deep-scan-weekly", **summary}
    except Exception as e:
        logger.error(f"Deep scan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{company}")
async def discover_roles_for_company_route(company: str):
    """Trigger role discovery for a specific company."""
    companies = load_companies()

    # Find the company in target list (case-insensitive)
    target = None
    for c in companies:
        if c["name"].lower() == company.lower():
            target = c
            break

    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Company '{company}' not found in target list",
        )

    try:
        result = await discover_for_company(target)

        # Auto-score any unscored roles (including ones just discovered)
        scored_count = 0
        score_failed = 0
        if result.get("new_roles", 0) > 0:
            scored_count, score_failed = await _auto_score_unscored()

        return {
            "status": "completed",
            **result,
            "auto_scored": scored_count,
            "score_failed": score_failed,
        }
    except Exception as e:
        logger.error(f"Discovery failed for {company}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
