"""Morning quick-apply digest (cloud-side).

For each NEW qualifying match (meets its company notification bar, discovered in
the last ~36h, still unreviewed), generate a ready-to-paste "quick-apply in 5
minutes" packet: company, title, apply URL, tier/score, which resume base to
attach, and the company-appropriate free-form answer(s). Email them via Resend.

Cost posture (Sam's choice): GENERATE-ONLY. One Claude call per role, with the
static persona cached (prompt caching) to keep token cost low. No separate LLM
reviewer calls here — grounding is enforced by the system prompt + locked-in
facts, and a deterministic post-scrub removes em/en dashes and flags any banned
phrases / AI-tells (advisory) using the same lexicons as the reviewer. Bounded
by settings.quick_apply_max per run.

Wired into the daily cron (discover_cron) so there is no new Vercel cron.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import resend

from app.config import get_settings, get_supabase_client, load_profile
from app.services.notifications import notification_threshold, _tier_badge
from app.services.agents.ai_tells import scan_ai_tells
from app.services.agents.locked_facts import BANNED_PHRASES, LOCKED_IN_FACTS_MARKDOWN

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"  # same model the app uses in prod

# Resume base to attach, by company (relative to the samresume folder).
RESUME_BASE = {
    "Anthropic": "anthropic/Sam_Prakash_Anthropic_Resume_v11_systems.docx",
    "OpenAI": "openai/Sam_Prakash_OpenAI_Resume_v10_api_agents.docx",
    "Google": "google/Sam_Prakash_Google_Resume_v1.docx",
    "Google DeepMind": "google/Sam_Prakash_Google_Resume_v1.docx",
    "xAI": "xAI/Sam_Prakash_Resume_xAI_v2.docx",
    "Amazon": None,  # internal transfer — no external resume
}

# Free-form field(s) each company's application asks for.
FIELD_SPEC = {
    "Anthropic": [("Why Anthropic (free-form field)", "200-400 words")],
    "OpenAI": [("Additional Information", "200-300 words")],
    "Google": [("Cover letter", "3 short paragraphs")],
    "Google DeepMind": [("Cover letter", "3 short paragraphs")],
    "xAI": [("Exceptional work", "under 100 words")],
    "Amazon": [
        ("Why are you interested in this role?", "<=250 words"),
        ("What are your relevant skills and experience?", "<=250 words"),
        ("Performance history (superpowers + a growth area)", "<=150 words"),
        ("Work contributions (2-3, each tagged to a Leadership Principle)", "short"),
    ],
}

SYSTEM = """You generate ready-to-paste job-application answers for Sam Prakash. Output JSON only.

ABSOLUTE GROUNDING RULE: Use ONLY facts present in Sam's profile and the locked-in facts below.
Never invent achievements, titles, metrics, employers, or quotes. If a fact is not in the source,
do not state it. This is a hard rule.

VOICE: plain, direct, concrete, first-person. No hype words (transformative, robust, seamless,
cutting-edge), no LLM-isms (delve, harness, underscore), no "not just X but Y", no clichés, no
marketing jargon, NO em dashes. Sound like a sharp operator writing quickly, not a marketer.

LOCKED-IN FACTS (use exact numbers/names; drop a fact rather than approximate it):
{locked}

You will receive Sam's profile JSON, the role (company, title, JD), and the exact field(s) the
application asks for with word targets. Produce each field, within its word target, grounded and
in Sam's voice.

Output JSON ONLY:
{{"fields": [{{"label": "<field label>", "text": "<the answer>"}}]}}"""


def _scrub_dashes(text: str) -> str:
    return text.replace("—", ", ").replace("–", "-")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_new_qualifying_roles(hours: int = 36, limit: int = 8) -> list[dict]:
    """Return new, unreviewed, live roles that meet their company's notification
    bar, newest+highest first, capped at `limit`. Each item: {role, score}."""
    sb = get_supabase_client()
    since = (_now() - timedelta(hours=hours)).isoformat()
    roles_resp = (
        sb.table("roles")
        .select("*")
        .gte("date_found", since)
        .eq("application_status", "unreviewed")
        .execute()
    )
    roles = roles_resp.data or []
    roles = [r for r in roles if r.get("is_live", True)]
    if not roles:
        return []

    ids = [r["id"] for r in roles]
    scores_resp = sb.table("role_scores").select("*").in_("role_id", ids).execute()
    by_role = {s["role_id"]: s for s in (scores_resp.data or [])}

    out = []
    for r in roles:
        s = by_role.get(r["id"])
        if not s or s.get("overall_score") is None:
            continue
        if int(s["overall_score"]) < notification_threshold(r.get("company")):
            continue
        out.append({"role": r, "score": s})

    out.sort(key=lambda x: int(x["score"]["overall_score"]), reverse=True)
    return out[:limit]


def _generate_fields(role: dict, profile: dict) -> tuple[list[dict], dict]:
    """One grounded Claude call. Returns (fields, usage)."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    company = role.get("company") or ""
    spec = FIELD_SPEC.get(company, [("Cover letter", "3 short paragraphs")])
    spec_text = "\n".join(f"- {label} (target: {target})" for label, target in spec)

    system_blocks = [
        # Cached static persona block (prompt caching → cheap repeat reads).
        {
            "type": "text",
            "text": SYSTEM.format(locked=LOCKED_IN_FACTS_MARKDOWN)
            + "\n\nSAM PROFILE JSON:\n" + json.dumps(profile, ensure_ascii=False),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    user = (
        f"COMPANY: {company}\nTITLE: {role.get('title')}\n"
        f"JD (truncated):\n{(role.get('raw_jd') or '')[:4000]}\n\n"
        f"FIELDS TO PRODUCE:\n{spec_text}\n\nReturn JSON only."
    )
    resp = client.messages.create(
        model=MODEL, max_tokens=1800, system=system_blocks,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {"fields": []}
    fields = data.get("fields", [])
    for f in fields:
        f["text"] = _scrub_dashes(f.get("text", ""))
    usage = {
        "input_tokens": getattr(resp.usage, "input_tokens", 0),
        "output_tokens": getattr(resp.usage, "output_tokens", 0),
    }
    return fields, usage


def _flag_fields(fields: list[dict]) -> list[str]:
    """Deterministic advisory flags (banned phrases + high-confidence AI-tells)."""
    flags: list[str] = []
    for f in fields:
        t = f.get("text", "")
        low = t.lower()
        for p in BANNED_PHRASES:
            if p in low:
                flags.append(f"banned phrase '{p}' in {f.get('label')}")
        for tell in scan_ai_tells(t):
            if tell.get("confidence") != "low":
                flags.append(f"{tell['rule']} in {f.get('label')}")
    return flags


def build_packets(limit: int | None = None) -> list[dict]:
    settings = get_settings()
    limit = limit or settings.quick_apply_max
    profile = load_profile()
    items = fetch_new_qualifying_roles(limit=limit)
    packets = []
    for it in items:
        role, score = it["role"], it["score"]
        company = role.get("company") or ""
        try:
            fields, usage = _generate_fields(role, profile)
        except Exception as e:
            logger.warning(f"quick-apply generation failed for {role.get('id')}: {e}")
            fields, usage = [], {"input_tokens": 0, "output_tokens": 0}
        packets.append({
            "company": company,
            "title": (role.get("title") or "").strip(),
            "url": role.get("url"),
            "tier": score.get("match_tier"),
            "score": score.get("overall_score"),
            "resume_base": RESUME_BASE.get(company, "(no base template — tailor from profile)"),
            "fields": fields,
            "flags": _flag_fields(fields),
            "usage": usage,
        })
    return packets


def render_html(packets: list[dict]) -> str:
    rows = []
    for p in packets:
        field_html = "".join(
            f"<p style='margin:6px 0 2px;font-weight:600'>{f.get('label','')}</p>"
            f"<div style='white-space:pre-wrap;background:#f6f8fa;border:1px solid #e1e4e8;"
            f"border-radius:6px;padding:10px;font-size:13px'>{(f.get('text') or '')}</div>"
            for f in p["fields"]
        )
        flag_html = ""
        if p["flags"]:
            flag_html = ("<p style='color:#b26a00;font-size:12px;margin:6px 0'>Review flags: "
                         + "; ".join(p["flags"]) + "</p>")
        rows.append(
            f"<div style='margin:0 0 22px;padding:14px;border:1px solid #d0d7de;border-radius:8px'>"
            f"<div style='font-size:16px;font-weight:700'>{p['title']} "
            f"<span style='color:#57606a;font-weight:400'>— {p['company']}</span></div>"
            f"<div style='font-size:13px;color:#57606a;margin:4px 0'>{_tier_badge(p['tier'])} "
            f"({p['score']}) · <a href='{p['url']}'>Apply</a> · Resume: {p['resume_base']}</div>"
            f"{flag_html}{field_html}</div>"
        )
    body = "".join(rows)
    has_openai = any(p["company"] == "OpenAI" for p in packets)
    cap = ("<p style='color:#b26a00'><strong>OpenAI cap:</strong> only 5 applications per 180 days "
           "— choose deliberately.</p>" if has_openai else "")
    return (
        f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:auto'>"
        f"<h2>Quick-apply packets — {datetime.now().strftime('%b %d, %Y')}</h2>"
        f"<p>{len(packets)} new qualifying match(es). Each is copy-paste ready; attach the noted "
        f"resume base and paste the field(s) below.</p>{cap}{body}"
        f"<p style='color:#8b949e;font-size:12px'>Generated by Job Search Intel. Drafts are grounded "
        f"in your profile; skim before submitting.</p></div>"
    )


def send_quick_apply_email(packets: list[dict]) -> bool:
    settings = get_settings()
    if not settings.resend_api_key or not settings.notification_email:
        logger.warning("quick-apply: Resend not configured; skipping send")
        return False
    if not packets:
        logger.info("quick-apply: no packets to send")
        return False
    resend.api_key = settings.resend_api_key
    params: resend.Emails.SendParams = {
        "from": "Job Search Intel <onboarding@resend.dev>",
        "to": [settings.notification_email],
        "subject": f"Quick-apply packets — {datetime.now().strftime('%b %d')} ({len(packets)} new)",
        "html": render_html(packets),
    }
    try:
        resend.Emails.send(params)
        return True
    except Exception as e:
        logger.error(f"quick-apply email failed: {e}")
        return False


def run_quick_apply(dry_run: bool = False, limit: int | None = None) -> dict:
    """Build packets and (unless dry_run) email them. Returns a summary."""
    packets = build_packets(limit=limit)
    tok_in = sum(p["usage"]["input_tokens"] for p in packets)
    tok_out = sum(p["usage"]["output_tokens"] for p in packets)
    sent = False
    if not dry_run:
        sent = send_quick_apply_email(packets)
    return {
        "packets": len(packets),
        "emailed": sent,
        "dry_run": dry_run,
        "tokens": {"input": tok_in, "output": tok_out},
        "items": [{"company": p["company"], "title": p["title"], "score": p["score"],
                   "flags": p["flags"]} for p in packets],
        "preview": packets if dry_run else None,
    }
