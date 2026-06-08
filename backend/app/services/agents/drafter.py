"""Stage 5: Drafter.

Thin wrapper around `application_tailor.generate_anthropic_package`. Builds an
extra-context string from the selected angles (first pass) or prior critic
findings (self-heal pass) and passes it through to the Claude tailoring call.

Output: artifact paths dict for the package (resume, cover_letter, why_anthropic).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.application_tailor import generate_anthropic_package

logger = logging.getLogger(__name__)


def _format_angles_for_drafter(angles: list[dict]) -> str:
    """Render the selected angles into a string the Claude drafter will read."""
    lines = ["The role-match analyzer selected these angles for you to lead with:\n"]
    for i, a in enumerate(angles, start=1):
        lines.append(f"{i}. **{a.get('angle', '?')}**")
        lines.append(f"   Rationale: {a.get('rationale', '')}")
        lines.append(f"   Evidence: {a.get('evidence_from_persona', '')}")
        lines.append(f"   Applies to: {a.get('applicable_to', 'all')}")
        lines.append("")
    return "\n".join(lines)


def _format_findings_for_drafter(findings: dict, attempt: int) -> str:
    """Render critic findings into a self-heal directive for the drafter."""
    lines = [
        f"SELF-HEAL PASS (attempt {attempt}). The critic flagged the following issues "
        "in your previous draft. Regenerate the package addressing every finding. "
        "Do not introduce new claims. Stay strictly grounded in the persona.\n"
    ]
    categories = [
        ("hallucinations", "Claims with no evidence in source data"),
        ("unsupported_claims", "Claims that need a citation but lack one"),
        ("factual_errors", "Claims that contradict source data"),
        ("tone_violations", "Voice rule violations"),
        ("length_violations", "Length target violations"),
        ("role_fit_drift", "Claims that drift from the role's actual hooks"),
    ]
    for key, label in categories:
        items = findings.get(key) or []
        if not items:
            continue
        lines.append(f"## {label} ({len(items)})")
        for it in items[:8]:  # cap to keep prompt size sane
            quote = it.get("quote", "")[:200]
            claim = it.get("claim", "")[:200]
            artifact = it.get("artifact", "?")
            note = (
                it.get("why_no_evidence")
                or it.get("rule")
                or it.get("why_off_target")
                or it.get("correct_value")
                or it.get("target")
                or ""
            )
            lines.append(f"- [{artifact}] {claim or quote}  ({note})")
        lines.append("")
    return "\n".join(lines)


async def draft(
    role_id: str,
    angles: list[dict],
    prior_findings: dict | None = None,
    attempt: int = 1,
) -> dict:
    """Run the drafter. Returns the dict from generate_anthropic_package().

    Args:
        role_id: The role to draft for.
        angles: Output of angle_selector, used to anchor the tailoring.
        prior_findings: Critic findings from the previous pass. Pass None on
            the first attempt; pass the findings dict for self-heal.
        attempt: 1 for first pass, 2 for self-heal.
    """
    angle_block = _format_angles_for_drafter(angles)
    finding_block = (
        _format_findings_for_drafter(prior_findings, attempt) if prior_findings else ""
    )
    extra_context = (angle_block + "\n\n" + finding_block).strip() if finding_block else angle_block

    logger.info(
        f"Drafter pass {attempt} for role {role_id} with {len(angles)} angles, "
        f"{'self-heal' if prior_findings else 'first-pass'}"
    )
    result = await generate_anthropic_package(
        role_id,
        force=True,  # pipeline gates upstream; we always want the docs produced
        extra_context=extra_context,
    )
    return result
