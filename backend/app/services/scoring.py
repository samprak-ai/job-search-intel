import json
import logging

import anthropic

from app.config import get_settings, get_supabase_client, load_profile

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """You are a job match scoring assistant. You evaluate how well a candidate's profile aligns with a job description.

Score the match across these 5 dimensions (each 0-100):
- domain_fit: How well the candidate's industry/domain experience matches
- technical_fit: How well the candidate's technical skills match requirements
- seniority_fit: How well the candidate's experience level matches the role level
- role_type_fit: How well the role aligns with the candidate's target role types
- h1b_likelihood: Likelihood the company sponsors H1B visas (based on company reputation and role type)

Apply a JD realism filter: posted requirements are often inflated. A candidate with 65%+ alignment on the right dimensions (domain, role type, seniority) is a strong match even if not every technical requirement is met.

HARD ROLE-TYPE EXCLUSIONS: The candidate is explicitly NOT pursuing engineering or solutions-architect tracks. If the job title contains "Engineer", "Engineering", "Solutions Architect", or "Solution Architect" (including variants like Software Engineer, Solutions Engineer, Sales Engineer, Customer Engineer, Forward Deployed Engineer, ML Engineer, Research Engineer, Engineering Manager, etc.), set role_type_fit to 10 or below, cap overall_score at 35, and use match_tier "Unlikely Match". Add a gap noting "Role title is on the candidate's exclusion list (engineer / solutions architect track)."

0→1 PREFERENCE FILTER (critical for role_type_fit scoring):
The candidate is a 0→1 builder-operator who owns business outcomes. He explicitly dislikes roles that are primarily about scaling, operating, or maintaining an existing function. Apply this lens when scoring role_type_fit:

SIGNALS OF 0→1 / BUILDER-OPERATOR ROLES (boost role_type_fit by +10 to +20, cap at 100):
- Role title includes: Labs, Incubation, Product Growth, AI Product Strategy, Applied AI (non-engineer), Head of New Products, GTM Systems, AI Automation Lead, AI Agents Lead, Chief of Staff (with build scope), Head of AI Product, Senior/Lead AI PM at AI-native companies, Strategic Projects, New Product Bets, Head of Programmatic Outcomes
- JD language: "build from scratch", "first hire in", "0-to-1", "define the playbook", "shape the roadmap", "new function", "greenfield", "prototype", "launch new", "incubate"
- Role scope includes talking to stakeholders, shipping MVPs, iterating based on feedback, then handing off to infra/eng teams

SIGNALS OF SCALING / OPERATIONS ROLES (downweight role_type_fit by -15 to -25):
- Role title includes: Planning Operations, BDR Operations, Sales Operations (without build scope), Activations (scaling existing), Revenue Operations (pure ops), Territory Design, Quota Operations, Enterprise Business Partner, Customer Success Operations (pure ops), Onboarding Lead, Enablement Manager
- JD language: "scale the existing", "maintain the operating model", "improve the current", "optimize the existing motion", "operate at larger scale", "manage the cadence", "run the process"
- Role scope is primarily about operating, reporting on, or scaling a function that already exists and has PMF

IMPORTANT: Apply this filter ON TOP of other dimensions. A scaling-ops role at an AI-native company may still have strong domain_fit and seniority_fit, but role_type_fit should reflect the mismatch with the candidate's 0→1 preference. In the rationale, explicitly note when a role is scaling-shaped (and therefore deprioritized) or builder-shaped (and therefore boosted).

Cap overall_score for pure-scaling roles at 82 (Strong Match ceiling), even if other dimensions are perfect — these should not qualify as Perfect Match.

Assign a match_tier based on overall score:
- "Perfect Match" — 90-100 overall, exceptional alignment across all dimensions
- "Strong Match" — 80-89 overall, strong alignment on key dimensions
- "Good Match" — 70-79 overall, solid alignment with some gaps
- "Possible Match" — 60-69 overall, partial alignment, notable gaps
- "Unlikely Match" — below 60 overall, significant misalignment

Respond with ONLY valid JSON in this exact format, no other text:
{
  "match_tier": "Perfect Match|Strong Match|Good Match|Possible Match|Unlikely Match",
  "overall_score": 0-100,
  "dimension_scores": {
    "domain_fit": 0-100,
    "technical_fit": 0-100,
    "seniority_fit": 0-100,
    "role_type_fit": 0-100,
    "h1b_likelihood": 0-100
  },
  "rationale": "2-3 sentence explanation of the scoring",
  "gaps": ["gap 1", "gap 2"],
  "cover_letter_angles": ["angle 1", "angle 2"]
}"""


def build_scoring_message(role: dict, profile: dict) -> str:
    """Build the user message with role and profile context."""
    return f"""## Job Posting
**Company:** {role['company']}
**Title:** {role['title']}
**Source:** {role.get('source', 'unknown')}
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
{chr(10).join('- ' + d for d in profile['differentiators'])}

Please score this job match."""


async def score_role(role_id: str, force: bool = False) -> dict:
    """Score a role against the candidate profile using Claude API.

    Skips scoring if the role is known to be stale (is_live=False), unless
    `force=True`. Stale roles that gain a score would surface as false
    Perfect Matches; we'd rather have no score than a misleading one.
    """
    settings = get_settings()
    supabase = get_supabase_client()
    profile = load_profile()

    # Fetch the role from DB
    result = supabase.table("roles").select("*").eq("id", role_id).execute()
    if not result.data:
        return None  # Signal to route handler for 404

    role = result.data[0]

    # Guard: don't score stale roles. Freshness check flips is_live to False
    # when a posting is no longer active, and we don't want such roles
    # bubbling up as Perfect Matches.
    if role.get("is_live") is False and not force:
        logger.info(
            f"Skipping scoring — role marked stale (is_live=False): "
            f"{role['title']} at {role['company']}"
        )
        return {
            "role_id": role_id,
            "company": role["company"],
            "title": role["title"],
            "skipped": True,
            "reason": "role is stale (is_live=False)",
        }

    logger.info(f"Scoring role: {role['title']} at {role['company']}")

    # Call Claude API
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SCORING_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_scoring_message(role, profile)}
        ],
    )

    # Parse Claude's JSON response (strip markdown fences if present)
    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]  # remove ```json line
        response_text = response_text.rsplit("```", 1)[0]  # remove closing ```
        response_text = response_text.strip()
    try:
        score_data = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Claude response as JSON: {response_text[:200]}")
        raise ValueError("Claude returned invalid JSON for scoring")

    # Store in role_scores table
    score_record = {
        "role_id": role_id,
        "match_tier": score_data["match_tier"],
        "overall_score": score_data["overall_score"],
        "dimension_scores": score_data["dimension_scores"],
        "rationale": score_data["rationale"],
        "gaps": score_data.get("gaps", []),
        "cover_letter_angles": score_data.get("cover_letter_angles", []),
    }
    supabase.table("role_scores").insert(score_record).execute()
    logger.info(
        f"Scored {role['title']} at {role['company']}: "
        f"{score_data['match_tier']} ({score_data['overall_score']})"
    )

    # Send email notification only for Perfect Match (90+) roles
    if score_data.get("overall_score", 0) >= 90:
        try:
            from app.services.notifications import send_perfect_match_email
            await send_perfect_match_email(role, score_data)
        except Exception as e:
            logger.error(f"Failed to send match notification: {e}")

        # Auto-generate a tailored application package for Anthropic Perfect Matches.
        # Non-blocking: scoring still succeeds even if tailoring fails.
        # Currently wired for Anthropic only; extend with per-company templates as needed.
        try:
            company_lower = (role.get("company") or "").lower().replace(" ", "")
            if "anthropic" in company_lower:
                from app.services.application_tailor import generate_anthropic_package
                pkg_result = await generate_anthropic_package(role_id)
                if pkg_result.get("status") == "generated":
                    logger.info(
                        f"Auto-generated application package for {role['title']}: "
                        f"{pkg_result['output_dir']}"
                    )
                else:
                    logger.info(
                        f"Skipped package generation for {role['title']}: "
                        f"{pkg_result.get('reason')}"
                    )
        except Exception as e:
            logger.error(f"Failed to auto-generate application package: {e}")

    return {
        "role_id": role_id,
        "company": role["company"],
        "title": role["title"],
        **score_data,
    }
