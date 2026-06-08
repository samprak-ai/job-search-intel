"""HTTP routes for the application_packages pipeline.

Endpoints:
  GET  /application-packages           — list (most recent first)
  GET  /application-packages/{role_id} — get one package by role_id
  POST /application-packages/{role_id}/run    — run the pipeline (idempotent)
  POST /application-packages/{role_id}/retry  — force re-run on a failed/skipped row
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.config import get_supabase_client
from app.services.agents.pipeline import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def list_packages(limit: int = Query(50, ge=1, le=500)):
    """List the most recent application packages."""
    sb = get_supabase_client()
    r = (
        sb.table("application_packages")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"items": r.data, "count": len(r.data)}


@router.get("/{role_id}")
async def get_package(role_id: str):
    """Get a single application package by role_id."""
    sb = get_supabase_client()
    r = sb.table("application_packages").select("*").eq("role_id", role_id).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="No package found for this role_id")
    return r.data[0]


@router.post("/{role_id}/run")
async def run_package(role_id: str):
    """Run the pipeline for this role (idempotent — short-circuits terminal states)."""
    try:
        result = await run_pipeline(role_id, allow_retry=False)
        return result
    except Exception as e:
        logger.exception(f"Pipeline run failed for {role_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{role_id}/retry")
async def retry_package(role_id: str):
    """Force the pipeline to re-run for this role, even if previously terminal."""
    try:
        result = await run_pipeline(role_id, allow_retry=True)
        return result
    except Exception as e:
        logger.exception(f"Pipeline retry failed for {role_id}")
        raise HTTPException(status_code=500, detail=str(e))
