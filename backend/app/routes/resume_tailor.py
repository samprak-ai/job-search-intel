import logging

from fastapi import APIRouter, HTTPException

from app.config import get_supabase_client
from app.services.resume_tailor import generate_resume_tailoring

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{role_id}")
async def create_resume_tailoring(role_id: str):
    """Generate resume tailoring advice for a specific role."""
    result = await generate_resume_tailoring(role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@router.get("/{role_id}")
async def get_resume_tailoring(role_id: str):
    """Retrieve existing resume tailoring for a role."""
    supabase = get_supabase_client()

    result = (
        supabase.table("resume_tailors")
        .select("*")
        .eq("role_id", role_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="No tailoring found for this role")

    return result.data[0]
