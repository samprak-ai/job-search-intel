import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.config import get_supabase_client
from app.services.forge import generate_session_config, generate_batch_sessions

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/session/batch")
async def create_batch_forge_sessions(
    skip_existing: Annotated[bool, Query()] = True,
):
    """Batch-generate Forge sessions for all Strong/Perfect Match roles.

    Finds all roles scored as Perfect Match or Strong Match and generates
    interview prep briefs for each, pushing them to Forge.
    Set skip_existing=false to regenerate even if a session already exists.
    """
    try:
        result = await generate_batch_sessions(skip_existing=skip_existing)
        return {"status": "completed", **result}
    except Exception as e:
        logger.error(f"Batch generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/session/{role_id}")
async def create_forge_session(role_id: str):
    """Generate a Forge session config for a role.

    Builds session config from role details, match score, and interview intel,
    then stores it in the sessions table.
    """
    result = await generate_session_config(role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Role not found")

    return {"status": "created", "session": result}


@router.get("/session/{role_id}")
async def get_forge_session(role_id: str):
    """Get the existing Forge session for a role."""
    supabase = get_supabase_client()

    result = (
        supabase.table("sessions")
        .select("*")
        .eq("role_id", role_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404, detail="No Forge session found for this role"
        )

    return result.data[0]
