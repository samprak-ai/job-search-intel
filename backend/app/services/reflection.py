"""Reflection pass — the self-improvement loop's tuning engine (Plane 3).

Reads the ground truth the system has accumulated (application_outcomes +
open detected_gaps + recent score distribution) and asks Claude to produce a
REVIEW REPORT: clustered gaps, calibration deltas, and concrete *proposed*
changes (new guards, scoring-rubric notes, discovery keywords, intel refresh).

It never auto-applies anything. Behavior changes (scoring/notifications) are
proposals for Sam to approve — the report is emailed and returned. Approved
scoring notes land in config/scoring_adjustments.json, which the scoring prompt
appends (a future wiring step).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic

from app.config import get_settings, get_supabase_client

logger = logging.getLogger(__name__)


REFLECTION_SYSTEM_PROMPT = """You are the reflection step of a self-improving job-search system owned by Sam Prakash.

You receive the system's accumulated ground truth:
1. application_outcomes — what actually happened after Sam engaged a role, each carrying the match_tier / overall_score the system PREDICTED at the time.
2. detected_gaps — runtime gaps the system flagged about itself (open ones).
3. score_distribution — recent score counts by company and tier.

Your job is to find where the system is systematically wrong and propose concrete, minimal fixes. Be specific and grounded in the data — do not invent patterns from thin evidence. If there isn't enough data yet, say so plainly and recommend waiting.

Focus on:
- CALIBRATION: is the rubric systematically over- or under-scoring by company, tier, or role shape? Quantify (e.g. "Amazon GTM predicted ~8pts high across 4 outcomes").
- TASTE: roles scored high that Sam skipped, or low that converted — what rubric signal is mis-weighted?
- RECURRING GAPS: clusters in detected_gaps that suggest a guard or a discovery/scoring change.

Output STRICT JSON only, no prose outside it:
{
  "data_sufficiency": "none|sparse|adequate",
  "headline": "one-sentence summary of the most important finding (or 'insufficient data')",
  "calibration_findings": [
    {"segment": "e.g. Amazon GTM", "direction": "over|under", "magnitude": "e.g. ~8 pts", "evidence_count": 0, "note": "..."}
  ],
  "proposed_changes": [
    {"kind": "scoring_note|new_guard|discovery_keyword|intel_refresh|other", "proposal": "concrete change", "rationale": "grounded in which data", "confidence": "low|medium|high"}
  ],
  "watch_items": ["things to revisit once more data arrives"]
}"""


def _gather_inputs() -> dict:
    """Pull outcomes, open gaps, and a score distribution snapshot."""
    sb = get_supabase_client()

    outcomes = (
        sb.table("application_outcomes")
        .select("role_id, status, outcome_date, predicted_match_tier, predicted_overall_score")
        .execute()
    ).data or []

    # Attach role labels for context.
    if outcomes:
        role_ids = [o["role_id"] for o in outcomes]
        roles = (
            sb.table("roles").select("id, title, company").in_("id", role_ids).execute()
        ).data or []
        role_map = {r["id"]: r for r in roles}
        for o in outcomes:
            r = role_map.get(o["role_id"], {})
            o["title"] = r.get("title")
            o["company"] = r.get("company")

    open_gaps = (
        sb.table("detected_gaps")
        .select("gap_type, severity, description, role_label, detail, detected_at")
        .eq("status", "open")
        .order("detected_at", desc=True)
        .limit(200)
        .execute()
    ).data or []

    # Score distribution by company/tier (live roles only).
    scores = (
        sb.table("role_scores").select("role_id, match_tier, overall_score").execute()
    ).data or []

    return {
        "outcomes": outcomes,
        "open_gaps": open_gaps,
        "score_count": len(scores),
    }


async def run_reflection() -> dict:
    """Run the reflection pass. Returns the structured review report."""
    inputs = _gather_inputs()
    settings = get_settings()

    outcome_n = len(inputs["outcomes"])
    gap_n = len(inputs["open_gaps"])

    # Short-circuit when there's genuinely nothing to reflect on — saves a call.
    if outcome_n == 0 and gap_n == 0:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_sufficiency": "none",
            "headline": "No outcomes or open gaps logged yet — nothing to reflect on.",
            "calibration_findings": [],
            "proposed_changes": [],
            "watch_items": ["Log application outcomes as you apply so calibration can begin."],
            "inputs_summary": {"outcomes": 0, "open_gaps": 0},
        }

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    user_msg = (
        f"## application_outcomes ({outcome_n})\n{json.dumps(inputs['outcomes'], indent=2)}\n\n"
        f"## open detected_gaps ({gap_n})\n{json.dumps(inputs['open_gaps'], indent=2)}\n\n"
        f"## score_distribution\nTotal scored roles: {inputs['score_count']}\n\n"
        "Produce the review report as strict JSON."
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=REFLECTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Reflection returned invalid JSON: {text[:300]}")
        report = {
            "data_sufficiency": "adequate",
            "headline": "Reflection produced unparseable output; see logs.",
            "calibration_findings": [],
            "proposed_changes": [],
            "watch_items": [],
        }

    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["inputs_summary"] = {"outcomes": outcome_n, "open_gaps": gap_n}
    logger.info(
        f"Reflection: {report.get('headline', '(no headline)')} "
        f"({len(report.get('proposed_changes', []))} proposed changes)"
    )
    return report


def send_reflection_email(report: dict) -> bool:
    """Email the review report. Proposals are for Sam to approve — nothing auto-applies."""
    import resend

    settings = get_settings()
    if not settings.resend_api_key or not settings.notification_email:
        logger.warning("Resend/notification email not configured — skipping reflection email")
        return False
    resend.api_key = settings.resend_api_key

    def _items(rows, render):
        return "".join(render(r) for r in rows) or "<li>None</li>"

    findings_html = _items(
        report.get("calibration_findings", []),
        lambda f: f"<li><b>{f.get('segment')}</b>: {f.get('direction')} by {f.get('magnitude')} "
                  f"({f.get('evidence_count')} outcomes) — {f.get('note','')}</li>",
    )
    changes_html = _items(
        report.get("proposed_changes", []),
        lambda c: f"<li>[{c.get('kind')} · {c.get('confidence')}] <b>{c.get('proposal')}</b><br>"
                  f"<span style='color:#6b7280;font-size:13px;'>{c.get('rationale','')}</span></li>",
    )
    watch_html = _items(report.get("watch_items", []), lambda w: f"<li>{w}</li>")
    s = report.get("inputs_summary", {})

    html = f"""
    <div style="font-family:-apple-system,sans-serif;max-width:640px;margin:0 auto;">
      <div style="background:#7c3aed;color:white;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">Reflection Report</h1>
        <p style="margin:6px 0 0;opacity:0.9;font-size:13px;">{s.get('outcomes',0)} outcomes · {s.get('open_gaps',0)} open gaps · data: {report.get('data_sufficiency')}</p>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 8px 8px;">
        <p style="font-size:15px;font-weight:600;color:#111827;">{report.get('headline','')}</p>
        <h3 style="font-size:14px;color:#374151;">Calibration findings</h3>
        <ul style="font-size:14px;color:#4b5563;">{findings_html}</ul>
        <h3 style="font-size:14px;color:#374151;">Proposed changes (your approval required)</h3>
        <ul style="font-size:14px;color:#4b5563;">{changes_html}</ul>
        <h3 style="font-size:14px;color:#374151;">Watch items</h3>
        <ul style="font-size:14px;color:#4b5563;">{watch_html}</ul>
      </div>
    </div>
    """
    try:
        resend.Emails.send({
            "from": "Job Search Intel <onboarding@resend.dev>",
            "to": [settings.notification_email],
            "subject": f"Reflection Report — {report.get('headline','')[:60]}",
            "html": html,
        })
        return True
    except Exception as e:
        logger.error(f"Failed to send reflection email: {e}")
        return False
