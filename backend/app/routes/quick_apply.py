"""Routes for the morning quick-apply digest.

  POST /quick-apply/cron     — build packets for new qualifying matches + email (CRON_SECRET)
  POST /quick-apply/preview  — build a small batch, return packets, do NOT email (CRON_SECRET)

The cron path is also invoked automatically inside /discover/cron (folded into the
daily run), so this endpoint is mainly for manual triggering and testing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.quick_apply import run_quick_apply

logger = logging.getLogger(__name__)
router = APIRouter()


def _auth(authorization: str | None) -> None:
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/cron")
async def quick_apply_cron(authorization: str | None = Header(default=None)):
    """Build packets for new qualifying matches and email them."""
    _auth(authorization)
    return run_quick_apply(dry_run=False)


@router.post("/preview")
async def quick_apply_preview(
    authorization: str | None = Header(default=None),
    limit: int = Query(2, ge=1, le=8),
):
    """Build a small batch and return packets without emailing (for testing).
    Bounded to <=8 to cap Claude spend."""
    _auth(authorization)
    return run_quick_apply(dry_run=True, limit=limit)
