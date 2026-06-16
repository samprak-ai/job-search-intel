"""Application-update ingestion — the inbox -> outcome -> Forge bridge.

Sam applies to roles; companies and their ATS reply by email. This service turns
those replies into structured outcome updates WITHOUT manual entry, and fires a
Forge interview-prep session on any positive movement (interview invite, online
assessment, or offer).

Design (decisions locked with Sam, 2026-06-15):
  - Runtime/trigger lives in a Cowork scheduled task using the Gmail connector.
    It reads candidate ATS emails and POSTs the raw batch to
    POST /application-updates/ingest. No Gmail token is wired into Railway.
  - This service owns classification + role-matching + the write. The write goes
    through services.outcomes.record_outcome() — the ONE return-path write path —
    so the calibration loop (prediction snapshot vs. actual + detected_gaps)
    stays intact. We do NOT write application_status from the Cowork task
    directly; bypassing record_outcome would fork the outcome state.
  - Positive movement (interview/OA/offer) -> generate_session_config() (Forge),
    which is idempotent (it deletes any prior session and regenerates).
  - Every processed message is logged to email_application_updates (message_id
    UNIQUE) so re-running the daily task never double-processes or double-fires.

Grounding / guardrails: classification is conservative. An email only updates a
role when (a) it is confidently an application-status email AND (b) it matches a
single role Sam actually engaged with (applied/interviewing/offer), or a single
role at that company. Ambiguous, marketing, job-alert, or this-app's-own digest
emails are reported and never written. Status only ever progresses (never
downgrades); a rejection is terminal and may arrive at any stage.
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher

import anthropic

from app.config import get_settings, get_supabase_client
from app.services.outcomes import map_role_status_to_outcome, record_outcome
from app.services.forge import generate_session_config

logger = logging.getLogger(__name__)

# Cheap, current model id (kept in selfcheck L18 ALLOWED_MODELS). Classification
# is a simple task, so we use Haiku rather than the prod Sonnet to bound spend.
CLASSIFY_MODEL = "claude-haiku-4-5-20251001"

# Bound spend / runtime per ingest call regardless of how many emails are sent.
MAX_EMAILS_PER_RUN = 25

# Detected email status -> role.application_status vocabulary.
DETECTED_TO_ROLE_STATUS = {
    "confirmation": "applied",
    "rejection": "rejected",
    "interview_invite": "interviewing",
    "online_assessment": "interviewing",  # OA is part of the interview funnel
    "offer": "offer",
}

# Detected statuses that should trigger a Forge prep session (positive movement).
POSITIVE_MOVEMENT = {"interview_invite", "online_assessment", "offer"}

# Status progression rank — we only ever move a role forward, never backward.
# rejected/ghosted/skipped are terminal/independent and handled separately.
STATUS_RANK = {"unreviewed": 0, "applied": 1, "interviewing": 2, "offer": 3}

# This app's own outbound digests must never be parsed as ATS mail.
OWN_SENDERS = ("onboarding@resend.dev", "resend.dev")
OWN_SUBJECT_PREFIXES = ("quick-apply packets", "job search intel")

CLASSIFY_SYSTEM = """You classify a single email about a job application. Output JSON only.

Decide if this email is an APPLICATION-STATUS update sent from a company or its
applicant tracking system (Greenhouse, Ashby, Lever, Gem, Workday, amazon.jobs,
etc.) to the candidate (Sam).

`status` is exactly one of:
- "confirmation"      : application received / under review / "thanks for applying to <role>"
- "rejection"         : not moving forward / position filled / decided not to proceed
- "interview_invite"  : invite to interview, phone screen, recruiter call, or to schedule one
- "online_assessment" : take-home, coding test, online assessment, HackerRank/Codility/CodeSignal link
- "offer"             : a job offer or offer letter
- "other"             : anything else — newsletters, marketing, job alerts/recommendations,
                        generic "thanks for your interest in <company>" mass mail, scheduling
                        logistics with no new stage, or this candidate's own automated digests

Also extract:
- company   : the hiring company (e.g. "Anthropic", "OpenAI", "Google", "Google DeepMind", "Amazon"). null if unclear.
- role_hint : the job title referenced, verbatim if present. null if absent.
- confidence: 0.0-1.0 that this is a genuine per-application status email for the chosen `status`.
- evidence  : <=160 chars quoting the phrase that determined the status.

Be conservative. A generic job-alert, recommendation, or marketing email is "other".
A real status email references a specific role or the candidate's own application.

Output JSON ONLY, no prose:
{"is_application_update": true, "status": "interview_invite", "company": "Anthropic", "role_hint": "Product Manager", "confidence": 0.0, "evidence": "..."}"""


# ── helpers ──────────────────────────────────────────────────────────────────

def _get(em: dict, *keys: str) -> str:
    """First non-empty value among keys (tolerant of Gmail connector shapes)."""
    for k in keys:
        v = em.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _message_id(em: dict) -> str:
    return _get(em, "message_id", "messageId", "id", "threadId", "thread_id")


def _is_own_digest(em: dict) -> bool:
    sender = _get(em, "from", "from_address", "sender", "fromAddress").lower()
    subject = _get(em, "subject", "title").lower()
    if any(s in sender for s in OWN_SENDERS):
        return True
    return any(subject.startswith(p) for p in OWN_SUBJECT_PREFIXES)


def _norm_company(c: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (c or "").lower())


def _company_matches(norm_query: str, db_company: str) -> bool:
    dbn = _norm_company(db_company)
    if not norm_query or not dbn:
        return False
    # DeepMind must not collapse into plain Google and vice-versa.
    if "deepmind" in norm_query:
        return "deepmind" in dbn
    if "deepmind" in dbn:
        return "deepmind" in norm_query
    return norm_query in dbn or dbn in norm_query


def _classify_email(em: dict) -> dict:
    """One conservative Claude call. Returns the parsed classification dict."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    sender = _get(em, "from", "from_address", "sender", "fromAddress")
    subject = _get(em, "subject", "title")
    body = _get(em, "body", "snippet", "text", "bodyText", "plain")[:4000]

    user = f"From: {sender}\nSubject: {subject}\n\n{body}"
    try:
        msg = client.messages.create(
            model=CLASSIFY_MODEL,
            max_tokens=400,
            system=CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
    except Exception as e:  # never let one bad email break the batch
        logger.warning(f"Classification failed: {e}")
        return {"is_application_update": False, "status": "other", "confidence": 0.0}

    data.setdefault("status", "other")
    data.setdefault("confidence", 0.0)
    return data


def _match_role(sb, cls: dict) -> dict | None:
    """Match a classification to exactly one role, or None if ambiguous/unknown.

    Preference order:
      1. Roles Sam actually engaged with (applied/interviewing/offer) at the company.
      2. All roles at the company (covers a fast rejection on a freshly-applied role).
    Title similarity disambiguates when there are multiple candidates.
    """
    company = cls.get("company")
    if not company:
        return None
    norm = _norm_company(company)

    rows = (
        sb.table("roles")
        .select("id, company, title, application_status, url")
        .execute()
        .data
        or []
    )
    cands = [r for r in rows if _company_matches(norm, r.get("company", ""))]
    if not cands:
        return None

    engaged = [
        r for r in cands
        if (r.get("application_status") or "") in ("applied", "interviewing", "offer")
    ]
    pool = engaged or cands

    role_hint = (cls.get("role_hint") or "").strip().lower()
    if role_hint:
        best, best_score = None, 0.0
        for r in pool:
            score = SequenceMatcher(None, role_hint, (r.get("title") or "").lower()).ratio()
            if score > best_score:
                best, best_score = r, score
        if best and best_score >= 0.55:
            return best
        # Title was given but matched nothing well. Accept only if there's a
        # single engaged role at the company (e.g. ATS reworded the title).
        if len(engaged) == 1:
            return engaged[0]
        return None

    # No title in the email (common for confirmations/rejections).
    if len(pool) == 1:
        return pool[0]
    if len(engaged) == 1:
        return engaged[0]
    return None


def _decide_status(role: dict, detected: str) -> str | None:
    """Resolve the new application_status, or None for a no-op.

    Rejection is terminal and applies from any stage. Otherwise status only
    moves forward (an 'application received' confirmation can't undo an invite).
    """
    target = DETECTED_TO_ROLE_STATUS.get(detected)
    if not target:
        return None
    current = (role.get("application_status") or "unreviewed").lower()
    if target == "rejected":
        return None if current == "rejected" else "rejected"
    if STATUS_RANK.get(target, 0) > STATUS_RANK.get(current, 0):
        return target
    return None


def _already_processed(sb, message_id: str) -> bool:
    if not message_id:
        return False
    try:
        existing = (
            sb.table("email_application_updates")
            .select("id")
            .eq("message_id", message_id)
            .limit(1)
            .execute()
        )
        return bool(existing.data)
    except Exception:
        return False  # log table missing -> don't block ingestion


def _log_processed(
    sb,
    message_id: str,
    em: dict,
    cls: dict,
    role: dict | None,
    applied_status: str | None,
    forge_fired: bool,
) -> None:
    try:
        sb.table("email_application_updates").insert(
            {
                "message_id": message_id or f"nomid:{hash(json.dumps(em, sort_keys=True, default=str))}",
                "from_address": _get(em, "from", "from_address", "sender", "fromAddress")[:300],
                "subject": _get(em, "subject", "title")[:500],
                "detected_company": cls.get("company"),
                "detected_status": cls.get("status"),
                "matched_role_id": role["id"] if role else None,
                "applied_status": applied_status,
                "forge_fired": forge_fired,
                "confidence": cls.get("confidence"),
                "evidence": (cls.get("evidence") or "")[:300],
            }
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to log processed email: {e}")


def _apply_update(role: dict, new_status: str) -> None:
    """Update the role and feed the single outcome write path (record_outcome).

    Mirrors PATCH /roles/{id} exactly so there's no parallel outcome state.
    """
    sb = get_supabase_client()
    sb.table("roles").update({"application_status": new_status}).eq("id", role["id"]).execute()
    outcome_status = map_role_status_to_outcome(new_status)
    if outcome_status:
        try:
            record_outcome(role, outcome_status)
        except Exception as e:  # never fail the status update on outcome logging
            logger.warning(f"record_outcome failed for {role['id']}: {e}")


async def _fire_forge(role_id: str) -> bool:
    try:
        await generate_session_config(role_id)
        return True
    except Exception as e:
        logger.warning(f"Forge auto-fire failed for {role_id}: {e}")
        return False


# ── entry point ──────────────────────────────────────────────────────────────

async def ingest_updates(emails: list[dict], dry_run: bool = False) -> dict:
    """Classify a batch of inbox emails, update matched roles, fire Forge.

    dry_run=True classifies + matches + proposes, but writes nothing (no DB
    update, no record_outcome, no Forge, no processed-log). Use for testing.
    """
    sb = get_supabase_client()
    emails = list(emails or [])[:MAX_EMAILS_PER_RUN]

    summary = {
        "received": len(emails),
        "dry_run": dry_run,
        "updated": 0,
        "forge_fired": 0,
        "skipped_already_processed": 0,
        "skipped_not_update": 0,
        "unmatched": 0,
        "no_op": 0,
        "items": [],
    }

    for em in emails:
        mid = _message_id(em)
        label = _get(em, "subject", "title")[:80]

        if _is_own_digest(em):
            summary["skipped_not_update"] += 1
            summary["items"].append({"subject": label, "result": "skipped_own_digest"})
            continue

        if not dry_run and _already_processed(sb, mid):
            summary["skipped_already_processed"] += 1
            summary["items"].append({"subject": label, "result": "already_processed"})
            continue

        cls = _classify_email(em)
        if not cls.get("is_application_update") or cls.get("status") == "other":
            summary["skipped_not_update"] += 1
            summary["items"].append({"subject": label, "result": "not_an_update", "detected": cls.get("status")})
            continue

        role = _match_role(sb, cls)
        if not role:
            summary["unmatched"] += 1
            summary["items"].append({
                "subject": label,
                "result": "unmatched",
                "detected_status": cls.get("status"),
                "company": cls.get("company"),
                "role_hint": cls.get("role_hint"),
            })
            continue

        new_status = _decide_status(role, cls["status"])
        if not new_status:
            summary["no_op"] += 1
            summary["items"].append({
                "subject": label,
                "result": "no_op_already_at_or_past",
                "role": f"{role['title']} @ {role['company']}",
                "current_status": role.get("application_status"),
                "detected_status": cls.get("status"),
            })
            continue

        item = {
            "subject": label,
            "role": f"{role['title']} @ {role['company']}",
            "from_status": role.get("application_status"),
            "to_status": new_status,
            "detected_status": cls["status"],
            "confidence": cls.get("confidence"),
        }

        if dry_run:
            item["result"] = "proposed"
            item["would_fire_forge"] = cls["status"] in POSITIVE_MOVEMENT
            summary["items"].append(item)
            continue

        _apply_update(role, new_status)
        summary["updated"] += 1

        forge_fired = False
        if cls["status"] in POSITIVE_MOVEMENT:
            forge_fired = await _fire_forge(role["id"])
            if forge_fired:
                summary["forge_fired"] += 1

        item["result"] = "updated"
        item["forge_fired"] = forge_fired
        summary["items"].append(item)

        _log_processed(sb, mid, em, cls, role, new_status, forge_fired)

    logger.info(
        f"Ingest complete: received={summary['received']} updated={summary['updated']} "
        f"forge_fired={summary['forge_fired']} unmatched={summary['unmatched']} dry_run={dry_run}"
    )
    return summary
