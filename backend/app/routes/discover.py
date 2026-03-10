import asyncio
import logging

from fastapi import APIRouter, HTTPException, Header
from typing import Annotated

from app.config import get_settings, get_supabase_client, load_companies
from app.services.discovery import discover_all, discover_for_company, cleanup_junk_roles, wipe_all_roles, backfill_departments
from app.services.jd_scraper import enrich_missing_jds

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("")
async def discover_roles():
    """Trigger role discovery across all target companies.

    Runs Brave Search queries for each company sequentially,
    deduplicates results, and stores new roles to the roles table.
    """
    try:
        results = await discover_all()
        total_new = sum(r["new_roles"] for r in results)
        return {
            "status": "completed",
            "companies_searched": len(results),
            "total_new_roles": total_new,
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
            targets = all_companies

        # Run discovery for each target company
        results = []
        for company in targets:
            summary = await discover_for_company(company)
            results.append(summary)
            await asyncio.sleep(0.5)

        total_new = sum(r["new_roles"] for r in results)

        # Auto-score any new unscored roles
        scored_count = 0
        score_failed = 0
        if total_new > 0:
            from app.services.scoring import score_role as score_fn
            supabase = get_supabase_client()
            scored_result = supabase.table("role_scores").select("role_id").execute()
            scored_ids = {r["role_id"] for r in scored_result.data}

            roles_result = supabase.table("roles").select("id, title, company").execute()
            unscored = [r for r in roles_result.data if r["id"] not in scored_ids]

            for role in unscored:
                try:
                    await score_fn(role["id"])
                    scored_count += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    score_failed += 1
                    logger.warning(f"Cron auto-score failed for {role['title']}: {e}")

        return {
            "status": "completed",
            "trigger": "cron",
            "companies_searched": len(results),
            "company_names": [c["name"] for c in targets],
            "total_new_roles": total_new,
            "auto_scored": scored_count,
            "score_failed": score_failed,
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cron discovery failed: {e}")
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
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Discovery failed for {company}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
