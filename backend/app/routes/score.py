import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from typing import Annotated

from app.config import get_supabase_client
from app.services.scoring import score_role

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/batch")
async def batch_score_unscored(
    limit: Annotated[int, Query()] = 100,
):
    """Score all unscored roles in batch.

    Finds roles without a score in role_scores and scores them sequentially.
    """
    supabase = get_supabase_client()

    # Get all role IDs that already have scores
    scored_result = supabase.table("role_scores").select("role_id").execute()
    scored_ids = {r["role_id"] for r in scored_result.data}

    # Get all roles
    roles_result = supabase.table("roles").select("id, title, company").execute()
    unscored = [r for r in roles_result.data if r["id"] not in scored_ids]

    if not unscored:
        return {"status": "completed", "total_unscored": 0, "scored": 0, "failed": 0}

    # Cap at limit
    to_score = unscored[:limit]
    scored = 0
    failed = 0
    results = []

    for role in to_score:
        try:
            result = await score_role(role["id"])
            scored += 1
            results.append({
                "company": role["company"],
                "title": role["title"],
                "match_tier": result["match_tier"],
                "overall_score": result["overall_score"],
            })
            logger.info(f"Batch scored [{scored}/{len(to_score)}]: {role['title']} at {role['company']}")
            # Small delay to avoid rate limits
            await asyncio.sleep(0.3)
        except Exception as e:
            failed += 1
            logger.warning(f"Batch scoring failed for {role['title']}: {e}")

    return {
        "status": "completed",
        "total_unscored": len(unscored),
        "scored": scored,
        "failed": failed,
        "results": results,
    }


@router.post("/{role_id}")
async def score_role_route(role_id: str):
    """Score a discovered role against Sam's profile.

    Sends the JD text + profile.json to Claude API for match scoring.
    Returns match tier, rationale, gaps, and cover letter angles.
    """
    try:
        result = await score_role(role_id)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Scoring failed for role {role_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if result is None:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")

    return {"status": "completed", **result}
