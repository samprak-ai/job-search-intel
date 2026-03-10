import logging

import resend

from app.config import get_settings

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
