"""Pipeline orchestrator.

Glues all stages together. Idempotent on role_id (the application_packages
table enforces a UNIQUE constraint on role_id). Self-heal-once: if the
first critic pass finds anything, the drafter re-runs with findings as
input, then the critic re-runs. If findings persist, the package is
forced to review_requested regardless of score.

Auto-send rule (per Sam's hybrid choice):
  auto_sent  iff  score >= 90 AND critic findings are empty
  review_requested  otherwise
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import get_supabase_client
from app.services.agents.angle_selector import select_angles
from app.services.agents.critic import count_findings, critique, has_findings
from app.services.agents.drafter import draft
from app.services.agents.emailer import send_package_email
from app.services.agents.gate import gate_check
from app.services.agents.persona_loader import load_persona, persona_snapshot
from app.services.agents.requirements import build_requirements

logger = logging.getLogger(__name__)


# Sentinel statuses that mean "do not re-run unless retry endpoint called"
TERMINAL_STATUSES = {"auto_sent", "awaiting_review", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_role_and_score(role_id: str) -> tuple[dict | None, dict | None]:
    sb = get_supabase_client()
    role_r = sb.table("roles").select("*").eq("id", role_id).execute()
    if not role_r.data:
        return None, None
    role = role_r.data[0]
    score_r = sb.table("role_scores").select("*").eq("role_id", role_id).execute()
    score = score_r.data[0] if score_r.data else None
    return role, score


def _upsert_package(role_id: str, fields: dict[str, Any]) -> str:
    """Insert or update the application_packages row for this role_id. Returns the id."""
    sb = get_supabase_client()
    # Use upsert on role_id (unique constraint enforced by migration)
    fields = dict(fields)
    fields["role_id"] = role_id
    result = sb.table("application_packages").upsert(
        fields, on_conflict="role_id", returning="representation"
    ).execute()
    if result.data:
        return result.data[0]["id"]
    # Fallback: re-fetch
    fetch = sb.table("application_packages").select("id").eq("role_id", role_id).execute()
    return fetch.data[0]["id"] if fetch.data else ""


def _set_status(role_id: str, status: str, **extra) -> None:
    """Mark the package row with a new status + any extra columns."""
    sb = get_supabase_client()
    update = {"status": status, **extra}
    sb.table("application_packages").update(update).eq("role_id", role_id).execute()


def _get_existing(role_id: str) -> dict | None:
    sb = get_supabase_client()
    r = sb.table("application_packages").select("*").eq("role_id", role_id).execute()
    return r.data[0] if r.data else None


async def run_pipeline(role_id: str, allow_retry: bool = False) -> dict:
    """Run the full Anthropic application package pipeline for one role.

    Args:
        role_id: The role to process.
        allow_retry: When True, ignores TERMINAL_STATUSES on existing rows
            (used by the retry endpoint to force re-run a failed/skipped package).

    Returns a result dict describing the final outcome.
    """
    # 1. Idempotency: short-circuit if we already have a terminal package
    existing = _get_existing(role_id)
    if existing and not allow_retry and existing["status"] in TERMINAL_STATUSES:
        logger.info(f"Pipeline: role {role_id} already in terminal status {existing['status']}; short-circuiting")
        return {
            "status": "already_processed",
            "package_id": existing["id"],
            "previous_status": existing["status"],
        }

    # 2. Fetch role + score
    role, score_data = _fetch_role_and_score(role_id)
    if not role:
        return {"status": "error", "reason": "role not found"}

    # 3. Initialize/reset the package row
    _upsert_package(role_id, {
        "status": "gating",
        "error": None,
        "error_stage": None,
        "self_healed": False,
        "findings_v1": None,
        "findings_v2": None,
        "send_mode": None,
        "email_sent_at": None,
    })

    try:
        # 4. Gate
        skip_reason = gate_check(role)
        if skip_reason:
            _set_status(role_id, "skipped", error=skip_reason, error_stage="gate")
            logger.info(f"Pipeline gated out: {role_id} — {skip_reason}")
            return {"status": "skipped", "reason": skip_reason}

        # 5. Persona
        _set_status(role_id, "aligning")
        persona = load_persona()

        # 6. Angles
        angle_result = await select_angles(persona, role)
        angles = angle_result["angles"]
        _set_status(
            role_id, "aligning",
            persona_used=persona_snapshot(persona),
            angles=angle_result,
        )

        # 7. Requirements
        requirements = build_requirements(role, angles)
        _set_status(role_id, "drafting", requirements=requirements)

        # 8. Draft (pass 1)
        draft_result = await draft(role_id, angles, prior_findings=None, attempt=1)
        if draft_result.get("status") != "generated":
            _set_status(
                role_id, "failed",
                error=draft_result.get("reason", "drafter did not produce artifacts"),
                error_stage="drafter_pass1",
            )
            return {"status": "failed", "reason": draft_result.get("reason"), "stage": "drafter_pass1"}

        artifact_paths = draft_result["files"]
        _set_status(role_id, "verifying", artifact_paths=artifact_paths)

        # 9. Critic (pass 1)
        findings_v1 = await critique(role, persona, artifact_paths, requirements, angles)
        _set_status(role_id, "verifying", findings_v1=findings_v1)

        findings_final = findings_v1
        self_healed = False

        # 10. Self-heal once if needed
        # Only trigger on semantic findings (hallucinations, factual errors, unsupported
        # claims, role_fit_drift) — NOT on tone or length violations alone.
        # Sending tone/length issues to the drafter causes it to rewrite sections that
        # were already correct, which can introduce new hallucinations or factual errors.
        semantic_keys = ("hallucinations", "unsupported_claims", "factual_errors", "role_fit_drift")
        has_semantic_findings = any(findings_v1.get(k) for k in semantic_keys)

        if has_semantic_findings:
            _set_status(role_id, "self_healing")
            draft_result_v2 = await draft(role_id, angles, prior_findings=findings_v1, attempt=2)
            if draft_result_v2.get("status") != "generated":
                _set_status(
                    role_id, "failed",
                    error=draft_result_v2.get("reason", "self-heal drafter failed"),
                    error_stage="drafter_pass2",
                )
                return {"status": "failed", "reason": draft_result_v2.get("reason"), "stage": "drafter_pass2"}

            artifact_paths = draft_result_v2["files"]
            self_healed = True

            findings_v2 = await critique(role, persona, artifact_paths, requirements, angles)
            findings_final = findings_v2
            _set_status(
                role_id, "verifying",
                artifact_paths=artifact_paths,
                findings_v2=findings_v2,
                self_healed=True,
            )

        # 11. Approval gate: Strict + score-gated
        overall_score = (score_data or {}).get("overall_score", 0) if score_data else 0
        final_clean = not has_findings(findings_final)

        if overall_score >= 90 and final_clean:
            send_mode = "auto_sent"
        else:
            send_mode = "review_requested"

        # 12. Email
        email_ok = await send_package_email(
            role=role,
            score_data=score_data or {},
            artifact_paths=artifact_paths,
            findings=findings_final,
            send_mode=send_mode,
            self_healed=self_healed,
        )

        final_status = send_mode if send_mode == "auto_sent" else "awaiting_review"
        _set_status(
            role_id,
            final_status,
            send_mode=send_mode,
            email_sent_at=_now() if email_ok else None,
        )

        result = {
            "status": final_status,
            "send_mode": send_mode,
            "self_healed": self_healed,
            "findings_count": count_findings(findings_final),
            "email_sent": email_ok,
            "artifact_paths": artifact_paths,
        }
        logger.info(
            f"Pipeline complete for {role.get('title')}: {final_status} "
            f"(score={overall_score}, findings={result['findings_count']}, healed={self_healed})"
        )
        return result

    except Exception as e:
        logger.exception(f"Pipeline failed for role {role_id}")
        _set_status(role_id, "failed", error=str(e), error_stage="exception")
        raise
