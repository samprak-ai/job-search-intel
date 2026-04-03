import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_roles(company: str | None = None, limit: int = 100):
    """List discovered roles, optionally filtered by company.

    Includes the latest score for each role if available.
    """
    supabase = get_supabase_client()

    # Select only fields needed for the dashboard listing — exclude raw_jd
    # which can be 10KB+ per role and slows the query significantly
    query = supabase.table("roles").select(
        "id, company, title, url, source, department, date_found, "
        "application_status, is_live, last_checked_at, created_at, "
        "role_scores(match_tier, overall_score, scored_at)"
    ).order("date_found", desc=True).limit(limit)

    if company:
        query = query.eq("company", company)

    result = query.execute()

    # Flatten: pick the most recent score per role
    roles = []
    for row in result.data:
        scores = row.pop("role_scores", [])
        if scores:
            latest = max(scores, key=lambda s: s["scored_at"] or "")
            row["match_tier"] = latest["match_tier"]
            row["overall_score"] = latest["overall_score"]
        else:
            row["match_tier"] = None
            row["overall_score"] = None
        roles.append(row)

    return {"roles": roles, "count": len(roles)}


@router.get("/{role_id}")
async def get_role(role_id: str):
    """Get a single role with its full score details and interview intel."""
    supabase = get_supabase_client()

    # Fetch role
    result = supabase.table("roles").select("*").eq("id", role_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Role not found")

    role = result.data[0]

    # Fetch scores
    scores = (
        supabase.table("role_scores")
        .select("*")
        .eq("role_id", role_id)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
    )
    role["score"] = scores.data[0] if scores.data else None

    # Fetch interview intel for this company
    intel = (
        supabase.table("interview_intel")
        .select("*")
        .eq("company", role["company"])
        .execute()
    )
    role["interview_intel"] = intel.data if intel.data else []

    # Fetch resume tailoring if exists
    tailoring = (
        supabase.table("resume_tailors")
        .select("*")
        .eq("role_id", role_id)
        .execute()
    )
    role["resume_tailor"] = tailoring.data[0] if tailoring.data else None

    # Fetch Forge session if exists
    session = (
        supabase.table("sessions")
        .select("*")
        .eq("role_id", role_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    role["session"] = session.data[0] if session.data else None

    return role


VALID_STATUSES = {"unreviewed", "applied", "interviewing", "offer", "rejected", "skipped"}


class StatusUpdate(BaseModel):
    application_status: str


@router.patch("/{role_id}")
async def update_role_status(role_id: str, body: StatusUpdate):
    """Update a role's application status."""
    if body.application_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    supabase = get_supabase_client()

    result = supabase.table("roles").select("id").eq("id", role_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Role not found")

    supabase.table("roles").update(
        {"application_status": body.application_status}
    ).eq("id", role_id).execute()

    return {"status": "updated", "role_id": role_id, "application_status": body.application_status}
