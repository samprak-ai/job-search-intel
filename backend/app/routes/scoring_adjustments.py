"""HTTP routes for scoring adjustments — one-click "approve" from /reflect.

Approving a reflection proposal writes a durable note here; build_scoring_message
appends active notes as a "Calibration adjustments" block, so the approval
actually changes future scores.

Endpoints:
  GET    /scoring-adjustments              — list (active by default)
  POST   /scoring-adjustments              — approve a note (scope global|company)
  DELETE /scoring-adjustments/{adj_id}     — deactivate (soft delete)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()


class AdjustmentIn(BaseModel):
    scope: str = Field("global", description="'global' or a company name")
    note: str
    source: str = "reflection"
    source_gap_id: str | None = None


@router.get("")
async def list_adjustments(active_only: bool = Query(True)):
    """List scoring adjustments, newest first."""
    sb = get_supabase_client()
    q = sb.table("scoring_adjustments").select("*").order("created_at", desc=True)
    if active_only:
        q = q.eq("active", True)
    r = q.execute()
    return {"items": r.data, "count": len(r.data)}


@router.post("")
async def approve_adjustment(body: AdjustmentIn):
    """Approve a calibration note → it starts shaping future scores."""
    note = body.note.strip()
    if not note:
        raise HTTPException(status_code=422, detail="note must not be empty")
    scope = body.scope.strip() or "global"

    sb = get_supabase_client()
    row = {
        "scope": scope,
        "note": note,
        "source": body.source,
        "source_gap_id": body.source_gap_id,
    }
    result = sb.table("scoring_adjustments").insert(row).execute()
    logger.info(f"Approved scoring adjustment [{scope}]: {note[:80]}")
    return result.data[0] if result.data else row


@router.delete("/{adj_id}")
async def deactivate_adjustment(adj_id: str):
    """Soft-delete: deactivate an adjustment so it stops affecting scores."""
    sb = get_supabase_client()
    r = sb.table("scoring_adjustments").update({"active": False}).eq("id", adj_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="adjustment not found")
    return r.data[0]
