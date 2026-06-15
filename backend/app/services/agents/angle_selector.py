"""Stage 3: Angle selector.

Per-role Claude call. Picks 2-3 strongest angles for Sam to lead with on THIS
role given his persona + JD. Output is used by the drafter to anchor its
tailoring and by the critic to verify the artifacts actually reflect the
selected angles.
"""

from __future__ import annotations

import json
import logging

import anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)


ANGLE_SELECTOR_SYSTEM_PROMPT = """You are selecting the 2-3 strongest angles for Sam Prakash to lead with on a specific Anthropic application.

You will be given:
1. Sam's persona (profile.json + interview narrative + locked-in facts)
2. The role title + full JD

Your task: pick 2-3 angles that are
- STRICTLY GROUNDED in Sam's actual persona (no fabrication)
- Directly address the role's most-important hooks (read the JD carefully)
- Differentiate Sam from the typical PM candidate at Anthropic (his 0-1 builder identity, AWS Startups insider position, and "builder + business owner" dual vantage)

For each angle, you must cite the evidence from the persona that grounds it.

Also output:
- `disqualifiers`: 1-3 things Sam should NOT claim for this role (where the JD asks for something he doesn't have)

Output JSON ONLY, no preamble:
{
  "angles": [
    {
      "angle": "Short imperative phrase describing the angle (e.g., 'Lead with AWS consumption-billing GTM insider angle')",
      "rationale": "Why this angle fits THIS role (1-2 sentences)",
      "evidence_from_persona": "Specific facts from the persona that ground this angle",
      "applicable_to": "cover_letter|resume|why_anthropic|all"
    }
  ],
  "disqualifiers": [
    "Specific claim Sam should NOT make and why"
  ]
}"""


async def select_angles(persona: dict, role: dict) -> dict:
    """Run the angle-selection Claude call. Returns {angles: [...], disqualifiers: [...]}."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Compact persona for the prompt — narrative is large, profile is structured.
    profile_text = json.dumps(persona["profile_json"], indent=2)
    narrative = persona["interview_narrative"][:8000]
    locked_facts = persona["locked_in_facts"]

    user_msg = f"""## Sam's profile.json
{profile_text}

## Sam's interview narrative (Block 1-5 positioning)
{narrative}

## Locked-in facts (these are non-negotiable)
{locked_facts}

## Role
**Title:** {role['title']}
**Company:** {role.get('company', 'Anthropic')}

**Job description:**
{role.get('raw_jd', '(no JD)')}

Select 2-3 angles now. Output JSON only."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=ANGLE_SELECTOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.JSONDecoder(strict=False).decode(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Angle selector returned invalid JSON: {response_text[:500]}")
        raise ValueError(f"Angle selector JSON parse failed: {e}")

    # Defensive shape check
    if "angles" not in parsed or not isinstance(parsed["angles"], list):
        raise ValueError(f"Angle selector output missing 'angles' list: {parsed}")
    parsed.setdefault("disqualifiers", [])

    logger.info(
        f"Angle selector picked {len(parsed['angles'])} angles for "
        f"{role['title']} at {role.get('company')}"
    )
    return parsed
