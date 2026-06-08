"""Stage 8: Emailer.

Sends the package to Sam via Resend with .docx attachments. Two body templates:
  - auto_sent: "ready to submit"
  - review_requested: "draft ready, findings inline"
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import resend

from app.config import get_settings
from app.services.agents.critic import count_findings

logger = logging.getLogger(__name__)


# Maximum findings per category to render inline in the email body (full list
# stays in the DB for audit).
MAX_FINDINGS_RENDERED_PER_CATEGORY = 5


def _read_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def _why_anthropic_body(why_md: str) -> str:
    """Strip the metadata header from why_anthropic.md, return body markdown."""
    if "---" in why_md:
        return why_md.split("---", 2)[-1].strip()
    return why_md.strip()


def _markdown_to_html(md: str) -> str:
    """Lightweight markdown → HTML for the bold-label structure used in why_anthropic."""
    # Bold **text** → <strong>text</strong>
    import re
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", md)
    # Paragraphs split on double newlines
    paragraphs = [p.strip() for p in html.split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def _render_findings_html(findings: dict) -> str:
    """Render critic findings as readable HTML for the review email body."""
    sections = [
        ("hallucinations", "Hallucinations (claims with no source)", "#dc2626"),
        ("unsupported_claims", "Unsupported claims (need a citation)", "#dc2626"),
        ("factual_errors", "Factual errors", "#dc2626"),
        ("role_fit_drift", "Role-fit drift", "#ea580c"),
        ("tone_violations", "Tone violations", "#ca8a04"),
        ("length_violations", "Length violations", "#ca8a04"),
    ]
    html = []
    for key, label, color in sections:
        items = findings.get(key) or []
        if not items:
            continue
        rendered = items[:MAX_FINDINGS_RENDERED_PER_CATEGORY]
        hidden = max(0, len(items) - len(rendered))
        html.append(f'<h3 style="color: {color}; margin: 18px 0 6px; font-size: 14px;">{label} ({len(items)})</h3>')
        html.append('<ul style="margin: 0 0 8px; padding-left: 20px; font-size: 13px; color: #374151;">')
        for it in rendered:
            artifact = it.get("artifact", "?")
            quote = (it.get("quote") or it.get("claim") or "")[:200]
            note = (
                it.get("why_no_evidence") or it.get("rule") or it.get("why_off_target")
                or it.get("correct_value") or it.get("target") or ""
            )
            note_str = f" <em style='color:#6b7280;'>({note})</em>" if note else ""
            html.append(f'<li><strong>[{artifact}]</strong> "{quote}"{note_str}</li>')
        if hidden:
            html.append(f'<li style="color:#9ca3af;">… and {hidden} more (see DB row)</li>')
        html.append("</ul>")
    return "".join(html)


def _build_email_html(
    role: dict,
    score_data: dict,
    artifact_paths: dict,
    findings: dict,
    send_mode: str,
    self_healed: bool,
) -> tuple[str, str]:
    """Return (subject, html_body) tuple."""
    title = role.get("title", "Unknown Role")
    score = (score_data or {}).get("overall_score", "?")
    tier = (score_data or {}).get("match_tier", "Strong Match")
    url = role.get("url", "")

    why_md = _read_text(artifact_paths["why_anthropic"])
    why_body = _why_anthropic_body(why_md)
    why_html = _markdown_to_html(why_body)

    total_findings = count_findings(findings)

    if send_mode == "auto_sent":
        subject = f"Auto-prepared: {title} at Anthropic ({score}/100) — ready to submit"
        header_bg = "#065f46"  # emerald
        banner = "Ready to submit"
        banner_sub = "Verification passed. Attachments below."
    else:
        subject = f"Draft ready for review: {title} at Anthropic ({score}/100)"
        header_bg = "#ca8a04"  # amber
        banner = "Draft ready for review"
        banner_sub = f"{total_findings} verification finding(s)"
        if self_healed:
            banner_sub += " after self-heal"

    findings_html = _render_findings_html(findings) if total_findings else ""

    html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 680px; margin: 0 auto;">
  <div style="background: {header_bg}; color: white; padding: 18px 22px; border-radius: 8px 8px 0 0;">
    <h1 style="margin: 0; font-size: 18px;">{banner}</h1>
    <p style="margin: 4px 0 0; opacity: 0.92; font-size: 13px;">{banner_sub}</p>
  </div>

  <div style="border: 1px solid #e5e7eb; border-top: none; padding: 20px 22px; border-radius: 0 0 8px 8px;">
    <h2 style="margin: 0 0 4px; font-size: 17px; color: #111827;">{title}</h2>
    <p style="margin: 0 0 14px; color: #6b7280; font-size: 13px;">
      <strong>{tier}</strong> · Score <strong>{score}/100</strong>
      {' · self-healed' if self_healed else ''}
    </p>

    <p style="margin: 12px 0;">
      <a href="{url}" style="display: inline-block; background: #2563eb; color: white; padding: 8px 14px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 500;">View Job Posting</a>
    </p>

    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 18px 0;">

    <h3 style="margin: 0 0 8px; font-size: 14px; color: #374151;">Why Anthropic (paste into the form's free-text field)</h3>
    <div style="background: #f9fafb; padding: 12px 14px; border-radius: 6px; font-size: 13px; color: #374151; line-height: 1.5;">
      {why_html}
    </div>

    {f'<hr style="border: none; border-top: 1px solid #e5e7eb; margin: 18px 0;"><h3 style="margin: 0 0 8px; font-size: 14px; color: #374151;">Verification findings</h3>{findings_html}' if findings_html else ''}

    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 18px 0;">
    <p style="margin: 0; font-size: 12px; color: #9ca3af;">
      Attachments: <strong>resume.docx</strong>, <strong>cover_letter.docx</strong>.
      Generated by the application package pipeline.
    </p>
  </div>
</div>
"""
    return subject, html


async def send_package_email(
    role: dict,
    score_data: dict,
    artifact_paths: dict,
    findings: dict,
    send_mode: str,
    self_healed: bool,
) -> bool:
    """Send the package email. Returns True on success."""
    settings = get_settings()
    if not settings.resend_api_key or not settings.notification_email:
        logger.warning("Resend API key or notification email not configured; skipping package email")
        return False

    resend.api_key = settings.resend_api_key

    subject, html = _build_email_html(role, score_data, artifact_paths, findings, send_mode, self_healed)

    # Encode attachments
    attachments = []
    for label, path_key in [("resume.docx", "resume"), ("cover_letter.docx", "cover_letter")]:
        path = artifact_paths.get(path_key)
        if not path:
            continue
        try:
            content_bytes = _read_bytes(path)
            attachments.append({
                "filename": label,
                "content": base64.b64encode(content_bytes).decode("ascii"),
            })
        except Exception as e:
            logger.error(f"Could not attach {label} from {path}: {e}")

    params: resend.Emails.SendParams = {
        "from": "Application Pipeline <onboarding@resend.dev>",
        "to": [settings.notification_email],
        "subject": subject,
        "html": html,
        "attachments": attachments,
    }

    try:
        email = resend.Emails.send(params)
        logger.info(
            f"Package email sent ({send_mode}) for {role.get('title')}: id={email.get('id') if isinstance(email, dict) else email}"
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send package email: {e}")
        return False
