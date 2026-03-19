"""Freshness check routes — validate whether role URLs are still live."""

import logging

from fastapi import APIRouter, HTTPException

from app.config import get_supabase_client
from app.services.freshness import check_all_freshness, check_role_freshness

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/check")
async def check_all_roles_freshness():
    """Check freshness for all active roles."""
    try:
        summary = await check_all_freshness()
        return {"status": "completed", **summary}
    except Exception as e:
        logger.error(f"Freshness check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check/{role_id}")
async def check_single_role_freshness(role_id: str):
    """Check freshness for a single role."""
    supabase = get_supabase_client()

    result = supabase.table("roles").select(
        "id, url, source, application_status"
    ).eq("id", role_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Role not found")

    role = result.data[0]
    update = await check_role_freshness(role)

    if update is None:
        return {
            "role_id": role_id,
            "status": "skipped",
            "reason": "Could not determine liveness (LinkedIn or transient error)",
        }

    supabase.table("roles").update(update).eq("id", role_id).execute()

    return {
        "role_id": role_id,
        "status": "checked",
        "is_live": update["is_live"],
        "last_checked_at": update["last_checked_at"],
    }
