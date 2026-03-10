"""Forge session generator — builds an AI-powered interview prep brief.

Uses Claude API to analyze the role's JD, the company's interview philosophy,
and Sam's profile to produce a strategic prep document that maps expected
questions to specific resume experiences.
"""

import json
import logging

import anthropic
import httpx

from app.config import get_settings, get_supabase_client, load_profile

logger = logging.getLogger(__name__)

FORGE_SYSTEM_PROMPT = """You are an expert interview strategist. Given a job description, candidate profile, match analysis, and any available interview intel about the company, produce a strategic interview preparation brief.

Your brief should:

1. **Company Interview Philosophy** — Based on the JD language, company reputation, and any interview intel provided, describe what this company values in interviews (e.g., "Anthropic emphasizes safety-consciousness and technical depth" or "They focus on real-world impact over theoretical knowledge"). Keep to 2-3 sentences.

2. **Expected Question Themes** — List 5-7 likely question themes for this specific role. For each theme, provide:
   - The theme name (e.g., "Customer-facing technical problem solving")
   - A representative question they might ask
   - Which specific part of the candidate's resume to leverage (be specific — name the project, role, or accomplishment)
   - A directional angle for the answer (1-2 sentences, not a full answer)

3. **Resume Leverage Map** — Identify the 3-4 strongest experiences from the candidate's background for THIS specific role, and explain WHY each one maps well (what signal it sends to the interviewer).

4. **Gap Mitigation** — For any identified gaps between the candidate and the role, suggest how to proactively address them (reframe, bridge from adjacent experience, or acknowledge and show eagerness to learn).

5. **Opening Pitch** — A 2-3 sentence "tell me about yourself" framing tailored to this specific role that leads with the candidate's most relevant differentiator.

Respond with ONLY valid JSON in this exact format, no other text:
{
  "company_interview_philosophy": "2-3 sentence description",
  "question_themes": [
    {
      "theme": "Theme name",
      "likely_question": "A question they might ask",
      "leverage_from_resume": "Specific experience/project to reference",
      "directional_angle": "How to approach the answer"
    }
  ],
  "resume_leverage_map": [
    {
      "experience": "Specific role/project/accomplishment",
      "why_it_maps": "Why this is strong for this role"
    }
  ],
  "gap_mitigation": [
    {
      "gap": "The gap identified",
      "strategy": "How to address it"
    }
  ],
  "opening_pitch": "Tailored 'tell me about yourself' framing"
}"""


def _build_forge_message(role: dict, profile: dict, score: dict | None, intel: list[dict]) -> str:
    """Build the user message with all available context."""

    # Score context
    score_section = ""
    if score:
        score_section = f"""
## Match Analysis
**Tier:** {score.get('match_tier', 'Unscored')}
**Overall Score:** {score.get('overall_score', 'N/A')}/100
**Rationale:** {score.get('rationale', 'N/A')}
**Gaps:** {', '.join(score.get('gaps', [])) or 'None identified'}
**Cover Letter Angles:** {', '.join(score.get('cover_letter_angles', [])) or 'None'}
"""

    # Interview intel context
    intel_section = ""
    if intel:
        intel_parts = []
        for item in intel:
            intel_parts.append(f"""- **Role Type:** {item.get('role_type', 'General')}
  - Interview Structure: {item.get('interview_structure', 'Unknown')}
  - Question Themes: {', '.join(item.get('question_themes', []))}
  - Emphasis Areas: {', '.join(item.get('emphasis_areas', []))}
  - Culture Signals: {', '.join(item.get('culture_signals', []))}""")
        intel_section = f"""
## Interview Intel (from research)
{chr(10).join(intel_parts)}
"""

    return f"""## Job Posting
**Company:** {role['company']}
**Title:** {role['title']}
**URL:** {role['url']}

**Description:**
{role.get('raw_jd', 'No description available')}
{score_section}
{intel_section}
## Candidate Profile
**Name:** {profile['name']}
**Location:** {profile['location']}
**Target Roles:** {', '.join(profile['target_role_types'])}
**Skills:** {', '.join(profile['skills'])}
**Education:** {profile['education']}

**Experience Summary:**
{profile['experience_summary']}

**Key Differentiators:**
{chr(10).join('- ' + d for d in profile['differentiators'])}

Please generate the interview preparation brief for this role."""


async def generate_session_config(role_id: str) -> dict | None:
    """Generate a Forge session config using Claude API.

    Analyzes the role JD, candidate profile, match score, and interview intel
    to produce a strategic interview prep brief.
    """
    settings = get_settings()
    supabase = get_supabase_client()
    profile = load_profile()

    # Fetch role
    result = supabase.table("roles").select("*").eq("id", role_id).execute()
    if not result.data:
        return None

    role = result.data[0]

    # Fetch latest score
    scores = (
        supabase.table("role_scores")
        .select("*")
        .eq("role_id", role_id)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
    )
    score = scores.data[0] if scores.data else None

    # Fetch interview intel for this company
    intel_result = (
        supabase.table("interview_intel")
        .select("*")
        .eq("company", role["company"])
        .execute()
    )
    intel = intel_result.data if intel_result.data else []

    logger.info(f"Generating Forge session for {role['title']} at {role['company']}")

    # Call Claude API
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=FORGE_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _build_forge_message(role, profile, score, intel)}
        ],
    )

    # Parse response
    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        session_config = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Forge response as JSON: {response_text[:200]}")
        raise ValueError("Claude returned invalid JSON for Forge session")

    # Upsert session record (delete old, insert new)
    supabase.table("sessions").delete().eq("role_id", role_id).execute()

    session_record = {
        "role_id": role_id,
        "session_config": session_config,
    }
    result = supabase.table("sessions").insert(session_record).execute()

    logger.info(
        f"Generated Forge session for {role['title']} at {role['company']}"
    )

    # Push to Forge app for interview practice
    await _push_to_forge(role, session_config)

    return result.data[0] if result.data else session_record


async def generate_batch_sessions(
    tiers: list[str] | None = None,
    skip_existing: bool = True,
) -> dict:
    """Batch-generate Forge sessions for all roles matching target tiers.

    By default generates for Perfect Match and Strong Match roles that
    don't already have a session.
    """
    if tiers is None:
        tiers = ["Perfect Match", "Strong Match", "Strong"]  # include old name

    supabase = get_supabase_client()

    # Get all scores in target tiers
    scores = (
        supabase.table("role_scores")
        .select("role_id, match_tier")
        .in_("match_tier", tiers)
        .execute()
    )

    if not scores.data:
        return {"eligible": 0, "generated": 0, "skipped": 0, "failed": 0, "details": []}

    # Deduplicate role_ids (a role could have multiple scores)
    role_ids = list({s["role_id"] for s in scores.data})

    # Optionally filter out roles that already have sessions
    skipped = 0
    if skip_existing:
        existing = (
            supabase.table("sessions")
            .select("role_id")
            .in_("role_id", role_ids)
            .execute()
        )
        existing_ids = {s["role_id"] for s in existing.data}
        original_count = len(role_ids)
        role_ids = [rid for rid in role_ids if rid not in existing_ids]
        skipped = original_count - len(role_ids)

    logger.info(
        f"Batch generation: {len(role_ids)} roles to process "
        f"({skipped} already have sessions)"
    )

    generated = 0
    failed = 0
    details = []

    for role_id in role_ids:
        try:
            result = await generate_session_config(role_id)
            if result:
                generated += 1
                details.append({
                    "role_id": role_id,
                    "status": "generated",
                    "company": result.get("session_config", {}).get("company_interview_philosophy", "")[:50],
                })
            else:
                failed += 1
                details.append({"role_id": role_id, "status": "not_found"})
        except Exception as e:
            failed += 1
            details.append({"role_id": role_id, "status": "error", "error": str(e)[:100]})
            logger.warning(f"Batch generation failed for {role_id}: {e}")

    logger.info(
        f"Batch generation complete: {generated} generated, {failed} failed, {skipped} skipped"
    )
    return {
        "eligible": len(role_ids) + skipped,
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "details": details,
    }


async def _push_to_forge(role: dict, session_config: dict) -> None:
    """Push interview prep data to the Forge app's import endpoint."""
    settings = get_settings()

    if not settings.forge_api_url or not settings.forge_import_key:
        logger.info("Forge API URL or import key not configured, skipping push")
        return

    payload = {
        "company": role["company"],
        "role_title": role["title"],
        "session_config": session_config,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.forge_api_url}/api/interview-prep/import",
                json=payload,
                headers={"Authorization": f"Bearer {settings.forge_import_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    f"Pushed {data.get('questions_imported', 0)} questions to Forge "
                    f"for {role['title']} at {role['company']}"
                )
            else:
                logger.warning(
                    f"Forge import returned {resp.status_code}: {resp.text[:200]}"
                )
    except Exception as e:
        logger.warning(f"Failed to push to Forge: {e}")
