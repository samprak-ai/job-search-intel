"""HTTP routes for application outcomes — the scoring loop's RETURN PATH.

Captures what actually happened after Sam engaged with a role so the scoring
rubric can later be calibrated (predicted tier/score vs. real outcome).

Endpoints:
  GET  /application-outcomes                  — list (most recent first)
  GET  /application-outcomes/calibration      — predicted vs. actual, for tuning
  GET  /application-outcomes/{role_id}         — get one outcome by role_id
  PUT  /application-outcomes/{role_id}         — log/update an outcome (upsert)
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_STATUSES = {"applied", "interview", "offer", "rejected", "ghosted", "skipped"}


class OutcomeIn(BaseModel):
    status: str = Field(..., description="applied|interview|offer|rejected|ghosted|skipped")
    notes: str | None = None
    outcome_date: date | None = None


@router.get("")
async def list_outcomes(limit: int = Query(100, ge=1, le=500)):
    """List logged outcomes, most recent first."""
    sb = get_supabase_client()
    r = (
        sb.table("application_outcomes")
        .select("*")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"items": r.data, "count": len(r.data)}


@router.get("/calibration")
async def calibration(limit: int = Query(500, ge=1, le=2000)):
    """Predicted (match_tier / overall_score at log time) vs. actual outcome.

    The ground-truth view for tuning the scoring rubric. Joins each outcome to
    its role for title/company context.
    """
    sb = get_supabase_client()
    outcomes = (
        sb.table("application_outcomes")
        .select("role_id, status, outcome_date, predicted_match_tier, predicted_overall_score")
        .limit(limit)
        .execute()
    ).data or []
    if not outcomes:
        return {"items": [], "count": 0}

    role_ids = [o["role_id"] for o in outcomes]
    roles = (
        sb.table("roles").select("id, title, company").in_("id", role_ids).execute()
    ).data or []
    role_map = {r["id"]: r for r in roles}

    items = []
    for o in outcomes:
        role = role_map.get(o["role_id"], {})
        items.append({
            **o,
            "title": role.get("title"),
            "company": role.get("company"),
        })
    return {"items": items, "count": len(items)}


@router.get("/{role_id}")
async def get_outcome(role_id: str):
    """Get the logged outcome for a role, if any."""
    sb = get_supabase_client()
    r = sb.table("application_outcomes").select("*").eq("role_id", role_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="No outcome logged for this role_id")
    return r.data[0]


@router.put("/{role_id}")
async def upsert_outcome(role_id: str, body: OutcomeIn):
    """Log or update the outcome for a role (one row per role, upserted).

    On first log, snapshots the role's current predicted match_tier and
    overall_score so later re-scoring can't rewrite the calibration history.
    """
    status = body.status.lower().strip()
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(VALID_STATUSES)}",
        )

    sb = get_supabase_client()

    # Role must exist.
    role = sb.table("roles").select("id").eq("id", role_id).execute()
    if not role.data:
        raise HTTPException(status_code=404, detail="role_id not found")

    fields: dict = {
        "role_id": role_id,
        "status": status,
        "notes": body.notes,
    }
    if body.outcome_date is not None:
        fields["outcome_date"] = body.outcome_date.isoformat()

    # Snapshot the prediction only on first log — preserve original prediction.
    existing = (
        sb.table("application_outcomes")
        .select("id, predicted_match_tier")
        .eq("role_id", role_id)
        .execute()
    )
    if not existing.data:
        score = (
            sb.table("role_scores")
            .select("match_tier, overall_score")
            .eq("role_id", role_id)
            .order("scored_at", desc=True)
            .limit(1)
            .execute()
        )
        if score.data:
            fields["predicted_match_tier"] = score.data[0].get("match_tier")
            fields["predicted_overall_score"] = score.data[0].get("overall_score")

    result = (
        sb.table("application_outcomes")
        .upsert(fields, on_conflict="role_id", returning="representation")
        .execute()
    )
    logger.info(f"Logged outcome '{status}' for role {role_id}")
    return result.data[0] if result.data else {"role_id": role_id, "status": status}
