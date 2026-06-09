"""HTTP route for the reflection pass (Plane 3).

  POST /reflect           — run reflection, return the review report
  POST /reflect?email=true — also email the report to the notification address

Intended to be invoked weekly (Railway cron) and on demand. Proposals are never
auto-applied; the report is for Sam to approve.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.services.reflection import run_reflection, send_reflection_email

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("")
async def reflect(email: bool = Query(False)):
    """Run the reflection pass over accumulated outcomes + gaps."""
    report = await run_reflection()
    emailed = False
    if email:
        emailed = send_reflection_email(report)
    return {"report": report, "emailed": emailed}
