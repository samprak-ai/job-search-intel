import json
import logging

import anthropic

from app.config import get_settings, get_supabase_client, load_profile

logger = logging.getLogger(__name__)

TAILORING_SYSTEM_PROMPT = """You are a resume tailoring strategist. Given a job description and a candidate's profile (with match scoring data), you produce a structured prioritization guide — NOT a full resume rewrite, but specific advice on how to reorder, emphasize, and reword existing resume content for this specific role.

You are advising a senior professional (11+ years) who has a strong, diverse background spanning GTM/Sales Operations at AWS and hands-on AI product building. The goal is to surface the RIGHT parts of their background for each role.

Respond with ONLY valid JSON in this exact format, no other text:
{
  "headline_suggestion": "A 1-line positioning statement tailored to this specific role (how to lead the resume header/summary)",
  "summary_rewrite": "A tailored 2-3 sentence professional summary rewritten for this specific role, incorporating relevant keywords and framing",
  "section_order": ["Ordered list of resume sections to prioritize, e.g.", "Professional Summary", "AI Projects", "AWS Experience", "Technical Skills", "Education"],
  "bullet_priorities": [
    {
      "original": "A bullet point or experience from their profile that is relevant",
      "action": "lead_with|reword|deprioritize",
      "reword_suggestion": "If action is 'reword' or 'lead_with', suggest how to reframe it. null if deprioritize.",
      "why": "Brief explanation of why this matters for the role"
    }
  ],
  "keywords_to_emphasize": ["keyword1", "keyword2", "keyword3"],
  "skills_to_highlight": ["Skill1", "Skill2"],
  "skills_to_deprioritize": ["Skill that is irrelevant to this role"]
}

Rules:
- bullet_priorities should have 5-8 items, covering the most important resume points to adjust
- bullet_priorities "original" field MUST be an exact copy of an actual bullet from the candidate's Work History or Project descriptions below — do not paraphrase
- keywords_to_emphasize should pull directly from the JD language
- section_order should list 4-7 sections in the optimal order for this role. Use recognizable section names like: "Independent AI Projects", "Professional AI Projects", "Experience" (for work history), "Capabilities", "Education"
- Be specific and actionable — reference actual JD requirements and actual profile content
- Consider the match gaps when suggesting rewording — help bridge those gaps through framing
- skills_to_highlight should be 3-6 items; skills_to_deprioritize should be 1-3 items

CRITICAL — Grounding constraint:
- The headline_suggestion and summary_rewrite must ONLY claim expertise, skills, or experience that is directly evidenced by the provided resume bullets and profile data. NEVER fabricate, infer, or invent capabilities to match the JD.
- If the candidate's background does not cover a JD requirement (e.g., quota management, compensation design), do NOT claim that expertise. Instead, frame adjacent strengths authentically — e.g., "operational analytics" instead of "quota governance" if the resume shows dashboards and reporting, not quota programs.
- Reword_suggestions must stay truthful to what the candidate actually did. You may reframe emphasis and language, but never change the substance of what happened.
- When there is a gap between the candidate's experience and the JD, acknowledge the gap implicitly by focusing on genuine strengths rather than fabricating alignment."""


def build_tailoring_message(role: dict, profile: dict, score: dict | None) -> str:
    """Build the user message with role, profile, and score context."""
    msg = f"""## Job Posting
**Company:** {role['company']}
**Title:** {role['title']}
**URL:** {role['url']}

**Description:**
{role.get('raw_jd', 'No description available')}

## Candidate Profile
**Name:** {profile['name']}
**Location:** {profile['location']}
**Target Roles:** {', '.join(profile['target_role_types'])}
**Skills:** {', '.join(profile['skills'])}
**Education:** {profile['education']}

**Experience Summary:**
{profile['experience_summary']}

**Key Differentiators:**
{chr(10).join('- ' + d for d in profile['differentiators'])}"""

    # Include structured work history bullets for precise matching
    if profile.get("work_history"):
        msg += "\n\n**Work History (Resume Bullets):**"
        for job in profile["work_history"]:
            msg += f"\n\n__{job['title']} — {job['company']} ({job['dates']})__"
            for bullet in job["bullets"]:
                msg += f"\n- {bullet}"

    if profile.get("projects"):
        msg += "\n\n**Independent Projects:**"
        for proj in profile["projects"]:
            msg += f"\n\n__{proj['title']} — {proj.get('subtitle', '')}__"
            if proj.get("description"):
                msg += f"\n{proj['description'][:300]}"

    if profile.get("professional_ai_projects"):
        msg += "\n\n**Professional AI Projects (Internal AWS):**"
        for proj in profile["professional_ai_projects"]:
            msg += f"\n\n__{proj['title']}__"
            if proj.get("description"):
                msg += f"\n{proj['description'][:300]}"
            if proj.get("outcome"):
                msg += f"\nOutcome: {proj['outcome'][:200]}"

    if score:
        msg += f"""

## Match Scoring Context
**Match Tier:** {score.get('match_tier', 'N/A')}
**Overall Score:** {score.get('overall_score', 'N/A')}/100
**Dimension Scores:** {json.dumps(score.get('dimension_scores', {}), indent=2)}

**Identified Gaps:**
{chr(10).join('- ' + g for g in score.get('gaps', []))}

**Cover Letter Angles:**
{chr(10).join('- ' + a for a in score.get('cover_letter_angles', []))}"""

    msg += "\n\nPlease produce a resume tailoring guide for this specific role."
    return msg


async def generate_resume_tailoring(role_id: str) -> dict:
    """Generate resume tailoring advice for a role using Claude API."""
    settings = get_settings()
    supabase = get_supabase_client()
    profile = load_profile()

    # Fetch the role
    result = supabase.table("roles").select("*").eq("id", role_id).execute()
    if not result.data:
        return None

    role = result.data[0]
    logger.info(f"Generating resume tailoring for: {role['title']} at {role['company']}")

    # Fetch existing score if available
    score_result = (
        supabase.table("role_scores")
        .select("*")
        .eq("role_id", role_id)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
    )
    score = score_result.data[0] if score_result.data else None

    # Call Claude API
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=TAILORING_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_tailoring_message(role, profile, score)}
        ],
    )

    # Parse response
    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        tailoring_data = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Claude tailoring response: {response_text[:200]}")
        raise ValueError("Claude returned invalid JSON for resume tailoring")

    # Upsert into resume_tailors table (UNIQUE on role_id)
    record = {
        "role_id": role_id,
        "tailoring": tailoring_data,
    }
    supabase.table("resume_tailors").upsert(record, on_conflict="role_id").execute()

    logger.info(f"Resume tailoring generated for {role['title']} at {role['company']}")

    return {
        "role_id": role_id,
        "company": role["company"],
        "title": role["title"],
        "tailoring": tailoring_data,
    }
