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

    # Fetch roles (without join — much faster)
    query = supabase.table("roles").select(
        "id, company, title, url, source, department, date_found, "
        "application_status, is_live, last_checked_at, created_at"
    ).order("date_found", desc=True).limit(limit)

    if company:
        query = query.eq("company", company)

    result = query.execute()

    # Fetch all scores in a single query (no join = faster)
    role_ids = [r["id"] for r in result.data]
    scores_map: dict[str, dict] = {}
    if role_ids:
        # Supabase .in_ can handle large lists; chunk if needed
        chunk_size = 200
        for i in range(0, len(role_ids), chunk_size):
            chunk = role_ids[i:i + chunk_size]
            scores_result = supabase.table("role_scores").select(
                "role_id, match_tier, overall_score, scored_at"
            ).in_("role_id", chunk).execute()
            for s in scores_result.data:
                rid = s["role_id"]
                # Keep the most recent score per role
                if rid not in scores_map or (s["scored_at"] or "") > (scores_map[rid]["scored_at"] or ""):
                    scores_map[rid] = s

    # Merge scores into roles
    roles = []
    for row in result.data:
        score = scores_map.get(row["id"])
        row["match_tier"] = score["match_tier"] if score else None
        row["overall_score"] = score["overall_score"] if score else None
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
