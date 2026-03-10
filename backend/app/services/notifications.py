import logging
from datetime import datetime, timezone

import resend

from app.config import get_settings, get_supabase_client

logger = logging.getLogger(__name__)


async def send_strong_match_email(role: dict, score_data: dict) -> bool:
    """Send email notification when a Strong match is found.

    Uses Resend API to email the notification address with role details.
    Returns True on success, False on failure (non-blocking).
    """
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
    overall_score = score_data.get("overall_score", "N/A")
    rationale = score_data.get("rationale", "No rationale provided")
    gaps = score_data.get("gaps", [])
    cover_angles = score_data.get("cover_letter_angles", [])

    gaps_html = "".join(f"<li>{g}</li>" for g in gaps) if gaps else "<li>None identified</li>"
    angles_html = "".join(f"<li>{a}</li>" for a in cover_angles) if cover_angles else "<li>None</li>"

    html_body = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
      <div style="background: #065f46; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0; font-size: 20px;">Strong Match Found!</h1>
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
            "subject": f"Strong Match: {title} at {company} ({overall_score}/100)",
            "html": html_body,
        }

        email = resend.Emails.send(params)
        logger.info(f"Strong match email sent for {title} at {company}: {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send strong match email: {e}")
        return False


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

    # ── Fetch today's roles + scores ──────────────────────────────────
    supabase = get_supabase_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    roles_result = (
        supabase.table("roles")
        .select("id, company, title, url, date_found")
        .gte("date_found", today)
        .order("company", desc=False)
        .execute()
    )
    today_roles = roles_result.data or []

    if not today_roles:
        logger.info("No roles with today's date_found — skipping digest")
        return False

    role_ids = [r["id"] for r in today_roles]

    scores_result = (
        supabase.table("role_scores")
        .select("role_id, match_tier, overall_score, rationale")
        .in_("role_id", role_ids)
        .execute()
    )
    score_map = {s["role_id"]: s for s in (scores_result.data or [])}

    # ── Group by tier ─────────────────────────────────────────────────
    tier_order = [
        "Perfect Match",
        "Strong Match",
        "Good Match",
        "Possible Match",
        "Unlikely Match",
    ]
    grouped: dict[str, list[dict]] = {t: [] for t in tier_order}
    grouped["Unscored"] = []

    for role in today_roles:
        score = score_map.get(role["id"])
        role["score"] = score
        if score:
            tier = score.get("match_tier", "Unscored")
            grouped.setdefault(tier, []).append(role)
        else:
            grouped["Unscored"].append(role)

    # ── Tier counts ───────────────────────────────────────────────────
    tier_counts = {t: len(grouped[t]) for t in tier_order if grouped[t]}
    unscored_count = len(grouped["Unscored"])

    # ── Build summary stats bar ───────────────────────────────────────
    stats_items = []
    for tier in tier_order:
        count = len(grouped[tier])
        if count:
            _, bg, text_color = TIER_COLORS[tier]
            label = tier.replace(" Match", "")
            stats_items.append(
                f'<span style="display:inline-block;background:{bg};color:{text_color};'
                f'padding:4px 10px;border-radius:6px;font-size:13px;font-weight:600;'
                f'margin:2px 4px 2px 0;">{count} {label}</span>'
            )
    if unscored_count:
        stats_items.append(
            f'<span style="display:inline-block;background:#f3f4f6;color:#6b7280;'
            f'padding:4px 10px;border-radius:6px;font-size:13px;font-weight:600;'
            f'margin:2px 4px 2px 0;">{unscored_count} Unscored</span>'
        )
    stats_html = " ".join(stats_items)

    # ── Top matches (Perfect + Strong): full detail ───────────────────
    top_roles = grouped["Perfect Match"] + grouped["Strong Match"]
    top_html = ""
    if top_roles:
        cards = []
        for role in top_roles:
            s = role["score"]
            tier = s["match_tier"]
            rationale = s.get("rationale", "")
            _, bg, _ = TIER_COLORS.get(tier, ("#374151", "#f9fafb", "#6b7280"))
            cards.append(f"""
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
        top_html = f"""
        <div style="margin-bottom:24px;">
          <h2 style="font-size:16px;color:#111827;margin:0 0 12px;">Top Matches</h2>
          {"".join(cards)}
        </div>"""

    # ── Other matches (Good + Possible): compact rows ─────────────────
    other_roles = grouped["Good Match"] + grouped["Possible Match"]
    other_html = ""
    if other_roles:
        rows = []
        for role in other_roles:
            s = role["score"]
            badge = _tier_badge(s["match_tier"])
            rows.append(
                f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:8px 0;font-size:13px;">{badge}</td>'
                f'<td style="padding:8px 8px;font-size:13px;"><strong>{role["company"]}</strong></td>'
                f'<td style="padding:8px 0;font-size:13px;">'
                f'<a href="{role["url"]}" style="color:#4f46e5;text-decoration:none;">{role["title"]}</a></td>'
                f'<td style="padding:8px 0;font-size:13px;text-align:right;font-weight:600;">{s["overall_score"]}</td>'
                f"</tr>"
            )
        other_html = f"""
        <div style="margin-bottom:24px;">
          <h2 style="font-size:16px;color:#111827;margin:0 0 12px;">Other Matches</h2>
          <table style="width:100%;border-collapse:collapse;">{"".join(rows)}</table>
        </div>"""

    # ── Unlikely count (just a note) ──────────────────────────────────
    unlikely_count = len(grouped["Unlikely Match"])
    unlikely_html = ""
    if unlikely_count:
        unlikely_html = (
            f'<p style="font-size:13px;color:#9ca3af;margin:0 0 20px;">'
            f"{unlikely_count} unlikely match{'es' if unlikely_count != 1 else ''} not shown.</p>"
        )

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
          {total_new} new role{'s' if total_new != 1 else ''} found across {companies_searched} {'companies' if companies_searched != 1 else 'company'}
        </p>
        <p style="margin:0 0 16px;font-size:13px;color:#6b7280;">
          {auto_scored} scored{f', {score_failed} failed' if score_failed else ''}
        </p>

        <div style="margin-bottom:20px;">{stats_html}</div>

        {top_html}
        {other_html}
        {unlikely_html}

        <div style="text-align:center;padding-top:8px;">
          {dashboard_html}
        </div>
      </div>
    </div>
    """

    # ── Send ──────────────────────────────────────────────────────────
    try:
        subject_parts = []
        for tier in ["Perfect Match", "Strong Match", "Good Match"]:
            count = len(grouped[tier])
            if count:
                label = tier.replace(" Match", "")
                subject_parts.append(f"{count} {label}")
        subject_summary = ", ".join(subject_parts) if subject_parts else f"{total_new} new"

        params: resend.Emails.SendParams = {
            "from": "Job Search Intel <onboarding@resend.dev>",
            "to": [settings.notification_email],
            "subject": f"Daily Digest: {subject_summary} — {formatted_date}",
            "html": html_body,
        }

        email = resend.Emails.send(params)
        logger.info(f"Daily digest email sent ({total_new} new roles): {email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send daily digest email: {e}")
        return False
