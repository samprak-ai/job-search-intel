"""HTTP routes for detected gaps — the auto-capture plane's read/manage API.

Endpoints:
  GET   /detected-gaps                  — list (filter by status/gap_type)
  POST  /detected-gaps                  — log a gap by hand (source='manual')
  PATCH /detected-gaps/{gap_id}/status  — open|guarded|resolved|wontfix
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_supabase_client
from app.services.gaps import log_gap

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_STATUSES = {"open", "guarded", "resolved", "wontfix"}


class ManualGapIn(BaseModel):
    gap_type: str = Field(..., description="e.g. discovery_miss, scoring_wrong, ux")
    description: str
    severity: str = "medium"
    role_id: str | None = None
    detail: dict | None = None


class StatusIn(BaseModel):
    status: str


@router.get("")
async def list_gaps(
    status: str | None = Query(None),
    gap_type: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """List detected gaps, newest first."""
    sb = get_supabase_client()
    q = sb.table("detected_gaps").select("*").order("detected_at", desc=True).limit(limit)
    if status:
        q = q.eq("status", status)
    if gap_type:
        q = q.eq("gap_type", gap_type)
    r = q.execute()
    return {"items": r.data, "count": len(r.data)}


@router.post("")
async def create_gap(body: ManualGapIn):
    """Log a gap by hand (e.g. 'we missed this role type')."""
    role_label = None
    if body.role_id:
        sb = get_supabase_client()
        role = sb.table("roles").select("title, company").eq("id", body.role_id).execute()
        if role.data:
            role_label = f"{role.data[0].get('title','?')} @ {role.data[0].get('company','?')}"
    row = log_gap(
        body.gap_type,
        body.description,
        severity=body.severity,
        role_id=body.role_id,
        role_label=role_label,
        detail=body.detail,
        source="manual",
    )
    if row is None:
        return {"status": "skipped", "reason": "an open gap of this type/role already exists"}
    return row


@router.patch("/{gap_id}/status")
async def update_status(gap_id: str, body: StatusIn):
    """Transition a gap's status (open → guarded/resolved/wontfix)."""
    status = body.status.lower().strip()
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{body.status}'. Must be one of: {sorted(VALID_STATUSES)}",
        )
    sb = get_supabase_client()
    update: dict = {"status": status}
    update["resolved_at"] = (
        datetime.now(timezone.utc).isoformat() if status in ("resolved", "wontfix") else None
    )
    r = sb.table("detected_gaps").update(update).eq("id", gap_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="gap not found")
    return r.data[0]
