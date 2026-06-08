import logging
from datetime import datetime, timezone

import resend

from app.config import get_settings, get_supabase_client

logger = logging.getLogger(__name__)


async def send_match_notification_email(role: dict, score_data: dict) -> bool:
    """Send email notification when a Strong (80+) or Perfect (90+) match is found.

    Uses Resend API to email the notification address with role details.
    Subject and header adapt to the role's actual match_tier so a Strong
    Match doesn't masquerade as a Perfect Match.

    Returns True on success, False on failure (non-blocking).
    Skips sending if role is stale (is_live=False) or score below 80.
    """
    overall_score = score_data.get("overall_score", 0)
    match_tier = score_data.get("match_tier", "Strong Match")

    # Guard: don't notify on stale roles or sub-Strong scores
    if role.get("is_live") is False:
        logger.info(
            f"Skipping match email — role is stale: "
            f"{role.get('title')} at {role.get('company')}"
        )
        return False
    if overall_score < 80:
        return False

    settings = get_settings()

    if not settings.resend_api_key or not settings.notification_email:
        logger.warning(
            "Resend API key or notification email not configured, skipping email"
        )
        return False

    resend.api_key = settings.resend_api_key

    company = role.get("company", "Unknown")
    title = role.get("title", "Unknown Role")
    url = role.get("url", "")
    rationale = score_data.get("rationale", "No rationale provided")
    gaps = score_data.get("gaps", [])
    cover_angles = score_data.get("cover_letter_angles", [])

    gaps_html = "".join(f"<li>{g}</li>" for g in gaps) if gaps else "<li>None identified</li>"
    angles_html = "".join(f"<li>{a}</li>" for a in cover_angles) if cover_angles else "<li>None</li>"

    # Tier-aware header color (matches TIER_COLORS used elsewhere)
    header_bg = "#065f46" if overall_score >= 90 else "#166534"  # Perfect = emerald, Strong = green

    html_body = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: {header_bg}; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0; font-size: 20px;">{match_tier} Found</h1>
        <p style="margin: 5px 0 0; opacity: 0.9;">{company}</p>
      </div>

      <div style="border: 1px solid #e5e7eb; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
        <h2 style="margin: 0 0 5px; font-size: 18px;">{title}</h2>
        <p style="color: #6b7280; margin: 0 0 15px;">Score: <strong>{overall_score}/100</strong></p>

        <div style="background: #f9fafb; padding: 15px; border-radius: 6px; margin-bottom: 15px;">
          <h3 style="margin: 0 0 8px; font-size: 14px; color: #374151;">Rationale</h3>
          <p style="margin: 0; font-size: 14px; color: #4b5563;">{rationale}</p>
        </div>

        <div style="margin-bottom: 15px;">
          <h3 style="font-size: 14px; color: #374151; margin: 0 0 8px;">Gaps to Address</h3>
          <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #4b5563;">{gaps_html}</ul>
        </div>

        <div style="margin-bottom: 20px;">
          <h3 style="font-size: 14px; color: #374151; margin: 0 0 8px;">Cover Letter Angles</h3>
          <ul style="margin: 0; padding-left: 20px; font-size: 14px; color: #4b5563;">{angles_html}</ul>
        </div>

        <a href="{url}" style="display: inline-block; background: #2563eb; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-size: 14px; font-weight: 500;">
          View Job Posting
        </a>
      </div>
    </div>
    """

    try:
        params: resend.Emails.SendParams = {
            "from": "Job Search Intel <onboarding@resend.dev>",
            "to": [settings.notification_email],
            "subject": f"{match_tier}: {title} at {company} ({overall_score}/100)",
            "html": html_body,
        }

        email = resend.Emails.send(params)
        logger.info(f"{match_tier} email sent for {title} at {company}: {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send match notification email: {e}")
        return False


# Back-compat alias — older imports of send_perfect_match_email still work.
send_perfect_match_email = send_match_notification_email


# ── Tier display helpers ──────────────────────────────────────────────

TIER_COLORS = {
    "Perfect Match": ("#065f46", "#ecfdf5", "#059669"),
    "Strong Match": ("#166534", "#f0fdf4", "#16a34a"),
    "Good Match": ("#1e40af", "#eff6ff", "#2563eb"),
    "Possible Match": ("#854d0e", "#fefce8", "#ca8a04"),
    "Unlikely Match": ("#374151", "#f9fafb", "#6b7280"),
}


def _tier_badge(tier: str) -> str:
    bg, _, text = TIER_COLORS.get(tier, ("#374151", "#f9fafb", "#6b7280"))
    return (
        f'<span style="display:inline-block;background:{bg};color:white;'
        f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">'
        f"{tier}</span>"
    )


async def send_daily_digest_email(
    companies_searched: int,
    total_new: int,
    auto_scored: int,
    score_failed: int,
    stale_found: int = 0,
) -> bool:
    """Send a daily digest email summarising the cron discovery results.

    Queries today's new roles + their scores and sends a grouped summary.
    Skips sending if no new roles were found.
    """
    if total_new == 0:
        logger.info("No new roles found today — skipping digest email")
        return False

    settings = get_settings()

    if not settings.resend_api_key or not settings.notification_email:
        logger.warning("Resend / notification email not configured, skipping digest")
        return False

    resend.api_key = settings.resend_api_key

    # ── Fetch today's scores + roles ──────────────────────────────────
    # Anchor on role_scores.scored_at (immutable) rather than
    # roles.date_found + is_live.  The freshness check runs in the same
    # cron pass and can flip is_live to False for newly-discovered roles
    # before the digest query executes, causing it to silently skip.
    # scored_at is set at scoring time and never mutated by freshness.
    supabase = get_supabase_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    scores_result = (
        supabase.table("role_scores")
        .select("role_id, match_tier, overall_score, rationale")
        .gte("scored_at", today)
        .execute()
    )
    today_scores = scores_result.data or []

    if not today_scores:
        logger.info("No roles scored today — skipping digest")
        return False

    role_ids = [s["role_id"] for s in today_scores]
    score_map = {s["role_id"]: s for s in today_scores}

    # Fetch role metadata — don't filter on is_live; freshness may have
    # already flipped it within the same cron pass.
    roles_result = (
        supabase.table("roles")
        .select("id, company, title, url, date_found, is_live")
        .in_("id", role_ids)
        .execute()
    )
    role_map = {r["id"]: r for r in (roles_result.data or [])}

    # ── Group by tier ─────────────────────────────────────────────────
    tier_order = [
        "Perfect Match",
        "Strong Match",
        "Good Match",
        "Possible Match",
        "Unlikely Match",
    ]
    grouped: dict[str, list[dict]] = {t: [] for t in tier_order}

    for score in today_scores:
        role = role_map.get(score["role_id"])
        if not role:
            continue
        role = dict(role)  # don't mutate the map
        role["score"] = score
        tier = score.get("match_tier", "Unlikely Match")
        grouped.setdefault(tier, []).append(role)

    # Only notify when at least one Strong (80+) or Perfect (90+) match is found.
    qualifying_roles = grouped["Perfect Match"] + grouped["Strong Match"]
    if not qualifying_roles:
        logger.info(
            f"Daily digest skipped — no Strong+ Matches today "
            f"(scan summary: {total_new} new, {auto_scored} scored)"
        )
        return False

    perfect_count = len(grouped["Perfect Match"])
    strong_count = len(grouped["Strong Match"])

    # Sort within each tier by overall_score descending so the strongest
    # candidates surface first within each section.
    perfect_roles = sorted(
        grouped["Perfect Match"],
        key=lambda r: r["score"].get("overall_score", 0),
        reverse=True,
    )
    strong_roles = sorted(
        grouped["Strong Match"],
        key=lambda r: r["score"].get("overall_score", 0),
        reverse=True,
    )

    def _render_cards(roles_subset):
        out = []
        for role in roles_subset:
            s = role["score"]
            tier = s["match_tier"]
            rationale = s.get("rationale", "")
            _, bg, _ = TIER_COLORS.get(tier, ("#374151", "#f9fafb", "#6b7280"))
            out.append(f"""
            <div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:12px;background:{bg};">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                  <strong style="font-size:15px;">{role['title']}</strong>
                  <span style="color:#6b7280;font-size:13px;margin-left:8px;">{role['company']}</span>
                </div>
                <span style="font-size:20px;font-weight:700;color:#4f46e5;">{s['overall_score']}</span>
              </div>
              <p style="margin:8px 0 0;font-size:13px;color:#4b5563;">{rationale}</p>
              <a href="{role['url']}" style="display:inline-block;margin-top:10px;color:#4f46e5;font-size:13px;text-decoration:none;font-weight:500;">View Posting &rarr;</a>
            </div>""")
        return "".join(out)

    sections = []
    if perfect_roles:
        sections.append(f"""
        <div style="margin-bottom:24px;">
          <h2 style="font-size:16px;color:#111827;margin:0 0 12px;">Perfect Matches Today ({perfect_count})</h2>
          {_render_cards(perfect_roles)}
        </div>""")
    if strong_roles:
        sections.append(f"""
        <div style="margin-bottom:24px;">
          <h2 style="font-size:16px;color:#111827;margin:0 0 12px;">Strong Matches Today ({strong_count})</h2>
          {_render_cards(strong_roles)}
        </div>""")
    top_html = "".join(sections)
    other_html = ""
    unlikely_html = ""

    # ── Dashboard link ────────────────────────────────────────────────
    dashboard_url = settings.frontend_url.rstrip("/") + "/dashboard" if settings.frontend_url else ""
    dashboard_html = ""
    if dashboard_url:
        dashboard_html = (
            f'<a href="{dashboard_url}" style="display:inline-block;background:#4f46e5;color:white;'
            f'padding:10px 24px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:500;">'
            f"Open Dashboard</a>"
        )

    # ── Assemble full email ───────────────────────────────────────────
    formatted_date = datetime.now(timezone.utc).strftime("%B %d, %Y")

    html_body = f"""
    <div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#4f46e5;color:white;padding:20px;border-radius:8px 8px 0 0;">
        <h1 style="margin:0;font-size:20px;">Daily Job Scan</h1>
        <p style="margin:5px 0 0;opacity:0.85;font-size:14px;">{formatted_date}</p>
      </div>

      <div style="border:1px solid #e5e7eb;border-top:none;padding:20px;border-radius:0 0 8px 8px;">
        <p style="margin:0 0 4px;font-size:15px;font-weight:600;color:#111827;">
          {perfect_count} Perfect + {strong_count} Strong today
        </p>
        <p style="margin:0 0 16px;font-size:13px;color:#6b7280;">
          {total_new} new role{'s' if total_new != 1 else ''} scanned across {companies_searched} {'companies' if companies_searched != 1 else 'company'}
        </p>

        {top_html}

        <div style="text-align:center;padding-top:8px;">
          {dashboard_html}
        </div>
      </div>
    </div>
    """

    # ── Send ──────────────────────────────────────────────────────────
    try:
        subject_parts = []
        if perfect_count:
            subject_parts.append(f"{perfect_count} Perfect")
        if strong_count:
            subject_parts.append(f"{strong_count} Strong")
        subject_summary = " + ".join(subject_parts) if subject_parts else "0"

        params: resend.Emails.SendParams = {
            "from": "Job Search Intel <onboarding@resend.dev>",
            "to": [settings.notification_email],
            "subject": f"Match Digest: {subject_summary} today — {formatted_date}",
            "html": html_body,
        }

        email = resend.Emails.send(params)
        logger.info(
            f"Match digest sent (perfect={perfect_count}, strong={strong_count}): {email}"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to send match digest: {e}")
        return False
