"""Stage 4: Requirements spec.

Returns a typed dict describing what the drafter must produce for a given
company + role. For v1 this is Anthropic-only and the spec is deterministic
(form conventions documented in CLAUDE.md). The spec is what the critic
validates against (length targets, must-include, must-not-claim, tone rules).
"""

from __future__ import annotations

from typing import Any


# Anthropic Greenhouse application form conventions (Sam's research).
# Resume + cover letter are uploaded; the "Why Anthropic" / additional info
# is a free-form text field on the form (200-400 word soft target).
ANTHROPIC_SPEC: dict[str, Any] = {
    "company": "Anthropic",
    "form_type": "greenhouse",
    "submission_artifacts": ["resume", "cover_letter", "why_anthropic"],
    "artifact_formats": {
        "resume": "docx",
        "cover_letter": "docx",
        "why_anthropic": "free_text_markdown",
    },
    "length_targets": {
        # (min, max) word counts. Hard fail outside the bounds.
        "why_anthropic_body": (260, 400),
        "cover_letter_body": (350, 550),
        "resume_pages": (1, 2),
    },
    "tone_rules": [
        "no em dashes",
        "no en dashes",
        "no banned jargon phrases (uniquely positioned, mission-critical, synergy, transformative, etc.)",
        "first-person, direct prose",
        "evidence-grounded claims only — no fabrication",
    ],
    "must_include": [
        # Phrases that should appear somewhere across the package
        "12+ years",
        "6.5+ years",
    ],
    "must_not_claim": [
        "engineer or solutions architect title",
        "deep ML engineering expertise",
        "experience Sam does not actually have",
    ],
    "why_anthropic_structure": [
        "3-4 themes with bold labels (e.g., '**Theme.**')",
        "At least one theme should differ from the cover letter's Why paragraph",
        "Lead with a concrete Claude-on-the-builder-side or AWS-consumption-billing angle when relevant",
    ],
}


def build_requirements(role: dict, angles: list[dict]) -> dict:
    """Produce the requirements spec for this role.

    Currently deterministic for Anthropic. The `angles` list is included so
    the drafter and critic have visibility into the selected angles.
    """
    spec = dict(ANTHROPIC_SPEC)
    spec["role_id"] = role["id"]
    spec["role_title"] = role.get("title")
    spec["selected_angles"] = angles
    return spec
