"""Routes for the email application-update bridge (inbox -> outcome -> Forge).

  POST /application-updates/ingest   — classify a batch of emails, update matched
                                       roles via the single outcome write path,
                                       and fire Forge on positive movement. Bearer CRON_SECRET.
  POST /application-updates/preview  — dry-run: classify + match + propose, write nothing. Bearer CRON_SECRET.

The trigger lives in a Cowork scheduled task (Gmail connector): it reads
candidate ATS emails and POSTs the raw batch here. Keeping the logic server-side
means the write stays on services.outcomes.record_outcome() — the one return-path
write path — so the calibration loop is not forked.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.application_updates import ingest_updates

logger = logging.getLogger(__name__)
router = APIRouter()


def _auth(authorization: str | None) -> None:
    settings = get_settings()
    if not settings.cron_secret:
        raise HTTPException(status_code=500, detail="CRON_SECRET not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class IngestIn(BaseModel):
    # Tolerant of Gmail-connector shapes: each item may carry any of
    # message_id/id, from/from_address, subject, snippet/body, date.
    emails: list[dict] = Field(default_factory=list)


@router.post("/ingest")
async def ingest(body: IngestIn, authorization: str | None = Header(default=None)):
    """Process inbox emails: update matched roles + fire Forge on positive movement."""
    _auth(authorization)
    return await ingest_updates(body.emails, dry_run=False)


@router.post("/preview")
async def preview(body: IngestIn, authorization: str | None = Header(default=None)):
    """Dry-run: classify + match + propose changes without writing anything."""
    _auth(authorization)
    return await ingest_updates(body.emails, dry_run=True)
