"""Outcome recording — the single write path for the scoring loop's return path.

Both the /application-outcomes API and the role status selector (PATCH /roles)
funnel through record_outcome(), so there's no parallel/competing outcome state.
On first log it snapshots the prediction (match_tier + overall_score) and
auto-evaluates a calibration gap.
"""

from __future__ import annotations

import logging

from app.config import get_supabase_client
from app.services.gaps import evaluate_outcome_gap

logger = logging.getLogger(__name__)

# Canonical outcome statuses (the application_outcomes enum).
OUTCOME_STATUSES = {"applied", "interview", "offer", "rejected", "ghosted", "skipped"}

# Map the role's application_status vocabulary → outcome status.
# None means "don't record an outcome" (e.g. unreviewed).
ROLE_STATUS_TO_OUTCOME = {
    "unreviewed": None,
    "applied": "applied",
    "interviewing": "interview",
    "offer": "offer",
    "rejected": "rejected",
    "ghosted": "ghosted",
    "skipped": "skipped",
}


def map_role_status_to_outcome(role_status: str | None) -> str | None:
    return ROLE_STATUS_TO_OUTCOME.get((role_status or "").lower().strip())


def record_outcome(
    role: dict,
    status: str,
    notes: str | None = None,
    outcome_date_iso: str | None = None,
) -> dict | None:
    """Upsert an outcome (one row per role) and auto-capture a calibration gap.

    `role` must include at least id, title, company. Returns the saved row, or
    None if `status` is not a recordable outcome.
    """
    status = (status or "").lower().strip()
    if status not in OUTCOME_STATUSES:
        return None

    sb = get_supabase_client()
    role_id = role["id"]
    fields: dict = {"role_id": role_id, "status": status, "notes": notes}
    if outcome_date_iso:
        fields["outcome_date"] = outcome_date_iso

    # Snapshot the prediction only on first log so re-scoring can't rewrite history.
    existing = (
        sb.table("application_outcomes").select("id").eq("role_id", role_id).execute()
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

    saved = (
        sb.table("application_outcomes")
        .upsert(fields, on_conflict="role_id", returning="representation")
        .execute()
    )
    row = saved.data[0] if saved.data else {"role_id": role_id, "status": status}
    logger.info(f"Recorded outcome '{status}' for role {role_id}")

    try:
        evaluate_outcome_gap(
            role, status, row.get("predicted_overall_score"), row.get("predicted_match_tier")
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(f"Outcome gap evaluation failed for {role_id}: {e}")
    return row
