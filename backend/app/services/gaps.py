"""Gap auto-capture — the system noticing its own runtime/product gaps.

`log_gap()` is the single write path into `detected_gaps`. It de-dupes against
existing OPEN gaps of the same (gap_type, role_id) so a repeated condition
doesn't spam the registry. The /reflect pass consumes the open gaps.

Callers:
  - application_outcomes route: prediction_mismatch / taste_mismatch
  - freshness service: stale_high_score
  - detected_gaps route: manual gaps logged by Sam
"""

from __future__ import annotations

import logging

from app.config import get_supabase_client

logger = logging.getLogger(__name__)

VALID_SEVERITIES = {"low", "medium", "high"}


def log_gap(
    gap_type: str,
    description: str,
    *,
    severity: str = "medium",
    role_id: str | None = None,
    role_label: str | None = None,
    detail: dict | None = None,
    source: str = "system",
) -> dict | None:
    """Insert a detected gap, de-duped against existing open gaps.

    Returns the inserted row, or None if a matching open gap already exists
    (or on failure — gap logging must never break the calling flow).
    """
    if severity not in VALID_SEVERITIES:
        severity = "medium"

    try:
        sb = get_supabase_client()

        # De-dupe: same type + same role still open → skip.
        existing = (
            sb.table("detected_gaps")
            .select("id")
            .eq("gap_type", gap_type)
            .eq("status", "open")
        )
        existing = existing.eq("role_id", role_id) if role_id else existing.is_("role_id", "null")
        if existing.execute().data:
            return None

        row = {
            "gap_type": gap_type,
            "severity": severity,
            "description": description,
            "role_id": role_id,
            "role_label": role_label,
            "detail": detail,
            "source": source,
        }
        result = sb.table("detected_gaps").insert(row).execute()
        logger.info(f"Logged detected gap [{gap_type}/{severity}]: {description[:80]}")
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"Failed to log detected gap ({gap_type}): {e}")
        return None


# ── Domain-specific detectors ───────────────────────────────────────────────

def evaluate_outcome_gap(
    role: dict,
    status: str,
    predicted_score: int | None,
    predicted_tier: str | None,
) -> dict | None:
    """Compare a logged outcome to the prediction and log a calibration gap.

    These aren't bugs — they're the ground-truth signal the rubric tunes on:
      - over-confident: predicted Strong+ (>=80) but rejected/ghosted
      - under-confident: predicted <70 but reached interview/offer
      - taste mismatch: scored very high (>=85) but Sam skipped it
    """
    if predicted_score is None:
        return None

    label = f"{role.get('title', '?')} @ {role.get('company', '?')}"
    common = dict(
        role_id=role.get("id"),
        role_label=label,
        detail={"status": status, "predicted_score": predicted_score, "predicted_tier": predicted_tier},
    )

    if status in ("rejected", "ghosted") and predicted_score >= 80:
        return log_gap(
            "prediction_overconfident",
            f"Predicted {predicted_tier} ({predicted_score}) but outcome was '{status}'.",
            severity="medium", **common,
        )
    if status in ("interview", "offer") and predicted_score < 70:
        return log_gap(
            "prediction_underconfident",
            f"Predicted only {predicted_score} but reached '{status}'.",
            severity="medium", **common,
        )
    if status == "skipped" and predicted_score >= 85:
        return log_gap(
            "taste_mismatch",
            f"Scored {predicted_score} ({predicted_tier}) but Sam skipped it — rubric may overvalue this role shape.",
            severity="low", **common,
        )
    return None
