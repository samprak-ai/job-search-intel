"""HTTP route for the reflection pass (Plane 3).

  POST /reflect           — run reflection, return the review report
  POST /reflect?email=true — also email the report to the notification address

Intended to be invoked weekly (Railway cron) and on demand. Proposals are never
auto-applied; the report is for Sam to approve.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query

from app.config import get_settings
from app.services.reflection import run_reflection, send_reflection_email

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("")
async def reflect(email: bool = Query(False)):
    """Run the reflection pass over accumulated outcomes + gaps (on demand)."""
    report = await run_reflection()
    emailed = False
    if email:
        emailed = send_reflection_email(report)
    return {"report": report, "emailed": emailed}


@router.post("/cron")
async def reflect_cron(authorization: Annotated[str | None, Header()] = None):
    """Cron-triggered weekly reflection. Always emails the report.

    Requires Bearer token matching CRON_SECRET (same pattern as /discover/cron).
    """
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")
    if not authorization or authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    report = await run_reflection()
    emailed = send_reflection_email(report)
    return {"status": "completed", "trigger": "cron", "emailed": emailed, "report": report}
