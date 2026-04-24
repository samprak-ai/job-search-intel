"""Application tailoring service.

Generates role-specific application packages (tailored resume, cover letter,
and Why-Company free-form answer) for Perfect Match roles. Currently supports
Anthropic; extend with per-company templates and prompts as other companies are
added.

Design:
  1. Loads source-of-truth profile and positioning context.
  2. Calls Claude API with a grounded prompt to produce a JSON tailoring object.
  3. Clones template .docx files and applies substitutions to anchored paragraphs.
  4. Writes artifacts + metadata to a per-role output folder.

Invocation:
  - On-demand per role: `await generate_anthropic_package(role_id)`
  - Auto-triggered from scoring.py when a Perfect Match is created at Anthropic.
  - Bulk backfill via `scripts/tailor_perfect_matches.py`.
"""

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from app.config import get_settings, get_supabase_client, load_profile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SAMRESUME_DIR = Path("/Users/Sam/Desktop/samresume")
ANTHROPIC_DIR = SAMRESUME_DIR / "anthropic"
OUTPUT_DIR = ANTHROPIC_DIR / "perfect_matches"

TEMPLATE_RESUME = ANTHROPIC_DIR / "Sam_Prakash_Anthropic_Resume_v11_systems.docx"
TEMPLATE_COVER = ANTHROPIC_DIR / "Sam_Prakash_Anthropic_CoverLetter_v7_systems.docx"

POSITIONING_CONTEXT_FILE = SAMRESUME_DIR / "_context" / "sam-profile.md"


# ---------------------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------------------

TAILORING_SYSTEM_PROMPT = """You are a resume-tailoring engine for Sam Prakash, producing application materials for roles at Anthropic. Your output is a single JSON object with specific fields.

FACTUAL GROUNDING (critical):
You may only use facts from Sam's profile, his existing AI projects, and his real work history. Never fabricate achievements, titles, companies, metrics, or quotes.

LOCKED-IN FACTS (use these exact numbers, names, and phrasings. DO NOT paraphrase or round. If you cannot fit a fact, drop it rather than approximating):

## Startup Pulse
- Duration compression: EXACTLY "6 weeks to under a week" (not "2 weeks", not "multi-week to same-week")
- Hours recovered: EXACTLY "600 hours per cycle across three individuals" (not 480, not "hundreds of hours", not "65%")
- Scale improvement: EXACTLY "10x scale improvement" (when cited)
- Time reduction: EXACTLY "70% reduction in report generation time" (not 65%, not "more than half")
- System scope: EXACTLY "2000+ strategic startups"
- Citation: "cited by Andy Jassy in Amazon's Q1 2026 earnings call"
- Board review: "served as a primary metric in Amazon's end-of-year board review for AWS startup competitive positioning" (use "primary metric", not "featured" or "included")
- Customer-facing users: "AWS's first AI-powered PCP and AI provider identification system"

## Monthly Top Startups Report
- Cohort size: EXACTLY "175 high-potential startups across 7 cohorts"
- Audience: "CEO Matt Garman's office throughout FY24"
- DO NOT conflate this 175 number with Startup Pulse's 2000+ scope. They are different.

## Top 100 AI Startups Report
- Audience: "Andy Jassy's office"
- Coordination: "130+ account teams"
- Sam developed the ranking methodology.

## AWS Internal AI Platforms
- Use: "Quick" and "PizzaBot"
- DO NOT use: "Amazon Q Spaces & Flows", "Amazon Q Flows", or "Amazon Q Spaces"
- Stack line: "Amazon Bedrock Agents · Salesforce MCP · Quick, PizzaBot"

## Project Names (canonical)
- Investor Pulse (formerly Portfolio Intelligence Engine; do NOT use the old name)
- Competitor Pulse (formerly FlankWatch / Competitive Threat Monitor; do NOT use old names)
- Loss Signal Validator
- Startup Pulse

## Sam's Title / Experience
- NO formal Product Manager title. Positions as "founder portfolio, measured by what runs in production."
- EXACTLY "11+ years total experience" AND "6.5+ years at AWS Startups". NEVER "11+ years at AWS Startups" (that conflates the two).
- Current role: Sr. GTM Sales Operations Manager, Startups, at Amazon Web Services (2022-Present).

## Live AI Products (shipped independently on Claude Code)
- Cloud-Intel (cloud-intel.vercel.app) - GTM intelligence platform; 4-tier attribution engine; 2,500 automated searches daily; 200+ VC-funded startups tracked
- Forge (forge-pi-livid.vercel.app) - AI practice platform; writing scored on 4 dimensions by Claude Sonnet; speaking scored on 5 dimensions via OpenAI Whisper transcription + Claude delivery analysis
- Job Search Intel (job-search-intel.vercel.app) - Job search automation; grounding constraint prevents LLM from fabricating expertise not evidenced in source data

These are THREE live AI products (count = 3), plus four AWS agentic systems. Total = seven AI systems in production.

SAM'S POSITIONING (from a structured interview):
- 0→1 builder-operator, not a scaling ops person. He ships MVPs then hands off to infrastructure teams.
- Strategic influence + creative autonomy are top priorities. Technical depth and commercial ambiguity rank lowest.
- 24-month horizon preferred. Hates "earn credibility then do the real work" cultures.
- Core problem he wants to solve: "assessing product market fit of an AI product."
- Unfair advantage: "builder + business owner" fused identity (founder DNA in a non-founder role).

VOICE RULES:
- NO em dashes (—). Use colons, periods, parens, or plain hyphens with spaces.
- No jargon inflation. Banned phrases: "uniquely positioned", "mission-critical", "synergy", "leverage" as verb, "transformative", "passionate about", "cross-functional alignment", "drive outcomes", "scale initiatives", "strategic stakeholder alignment".
- Plain, direct prose. Concrete proof points over abstract claims.

TASK:
Given the JD, produce a JSON object with these fields:

{
  "subtitle": "Resume subtitle (under 100 chars, 2-3 elements separated by ' · '). Must signal the role category (AI Product Builder | Systems & Automation | GTM Builder-Operator | etc.) AND experience distinction. Examples: 'AI Product Builder · Founder-Adjacent · 11+ Years GTM/Strategy (6.5+ at AWS)' or 'AI Systems & Automation · Builder-Operator · 11+ Years (6.5+ at AWS)'.",

  "professional_summary": "80-120 word Professional Summary tuned to THIS specific role. Must distinguish 11+ total from 6.5+ AWS. Must cite concrete builds. Must name the honest gap if relevant (e.g., 'no formal PM title yet'). Anchor on role-relevant achievements.",

  "why_anthropic": "300-360 word free-form 'Why Anthropic' answer for the application form. Structure: 3-4 themes with bold labels (use **Label.** markdown format). Typical structure: (1) 'The stack I already build on' (Claude Code/API/MCP depend-on-daily evidence), (2) a role-specific fit theme, (3) a stage/problem-shape theme, (4) optional honest note on background. Different angle from the cover letter's Why paragraph. No em dashes.",

  "cover_letter_para_1": "Opening paragraph anchoring on the specific role scope with one strongest proof point upfront. 80-120 words. Often leads with 'X is what I've been building' framing if the role is about a specific product area.",

  "cover_letter_para_2": "Concrete evidence paragraph. Lead with Startup Pulse (most credible single proof point, with the Q1 2026 earnings call citation) and 1-2 other builds relevant to THIS specific role. 120-180 words.",

  "cover_letter_para_3": "Why Anthropic specific to this role. Different angle from the free-form Why Anthropic field. Focus on why this ROLE at Anthropic is the highest-leverage version of what Sam's already doing. 80-120 words.",

  "cover_letter_para_4": "Close. Often 'founder portfolio, not a founder resume' or 'that's the version of this work I want to do at the company whose research I already build on.' 60-80 words.",

  "key_role_hooks": ["3-5 specific keywords/phrases from the JD that the application should echo. These are for internal tracking; they help verify the tailoring landed."]
}

Output ONLY the JSON object. No preamble, no markdown fencing."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Turn a role title into a filesystem-safe slug."""
    # Strip common prefixes
    s = title
    s = re.sub(r"^Job Application for ", "", s, flags=re.I)
    s = re.sub(r" at Anthropic$", "", s, flags=re.I)
    s = re.sub(r" - Greenhouse$", "", s, flags=re.I)
    # Normalize
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s[:80] or "role"


def _load_positioning_summary() -> str:
    """Load a compact summary of Sam's positioning context from sam-profile.md."""
    if not POSITIONING_CONTEXT_FILE.exists():
        return ""
    try:
        content = POSITIONING_CONTEXT_FILE.read_text(encoding="utf-8")
        # Return up to first ~8000 chars (context file is large; we send the top-relevant portion)
        return content[:8000]
    except Exception as e:
        logger.warning(f"Could not load positioning context: {e}")
        return ""


def _scrub_dashes(text: str) -> str:
    """Replace em/en dashes with plain hyphens (per voice rules)."""
    if not isinstance(text, str):
        return text
    # En dashes and em dashes -> plain hyphens
    text = text.replace(" — ", " - ").replace("—", "-")
    text = text.replace(" – ", " - ").replace("–", "-")
    return text


def _scrub_tailoring(tailoring: dict) -> dict:
    """Apply post-processing to Claude's tailoring output."""
    scrubbed = {}
    for k, v in tailoring.items():
        if isinstance(v, str):
            scrubbed[k] = _scrub_dashes(v)
        elif isinstance(v, list):
            scrubbed[k] = [_scrub_dashes(x) if isinstance(x, str) else x for x in v]
        else:
            scrubbed[k] = v
    return scrubbed


def _call_claude_for_tailoring(role: dict, score_data: dict | None, profile: dict) -> dict:
    """Invoke Claude API to produce the tailoring JSON object."""
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    profile_text = json.dumps(profile, indent=2)
    positioning = _load_positioning_summary()

    user_msg = f"""## Sam's Profile
{profile_text}

## Sam's Positioning Context (from structured interview)
{positioning}

## Role to tailor for
**Title:** {role['title']}
**Company:** {role['company']}
**URL:** {role['url']}

**Job Description:**
{role.get('raw_jd', '(No JD text stored; use only title + company to infer role scope, but note the limited context)')}

## Prior score
{json.dumps(score_data or {}, indent=2) if score_data else '(no score data)'}

Produce the tailoring JSON now."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=TAILORING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    response_text = message.content[0].text.strip()
    # Strip markdown fences if Claude slipped one in
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON for tailoring: {response_text[:500]}")
        raise ValueError(f"Tailoring JSON parse failed: {e}")


def _apply_tailoring_to_resume(source_path: Path, dest_path: Path, tailoring: dict) -> None:
    """Clone the template resume and apply subtitle + professional summary substitutions."""
    # Use the verified docx_lib helpers from the samresume tooling folder
    import sys
    tool_dir = str(SAMRESUME_DIR / "_tools")
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    from docx_lib import (  # type: ignore
        Document,
        find_paragraph_containing,
        replace_whole_paragraph,
        full_para_text,
    )

    shutil.copy(source_path, dest_path)
    doc = Document(dest_path)

    # Replace subtitle (line typically contains "Builder" or "Agentic" — use first line after contact)
    # Safer: find the specific known subtitle text in the template
    for anchor in [
        "Business Systems & AI Operations",
        "AI Product Builder",
        "AI Systems & Automation",
        "GTM Strategy",
    ]:
        p = find_paragraph_containing(doc, anchor)
        if p:
            replace_whole_paragraph(p, tailoring["subtitle"])
            break

    # Replace Professional Summary (the paragraph right after the "PROFESSIONAL SUMMARY" header)
    paragraphs = list(doc.paragraphs)
    for i, p in enumerate(paragraphs):
        if full_para_text(p).strip() == "PROFESSIONAL SUMMARY":
            # Next non-empty paragraph is the summary body
            for j in range(i + 1, len(paragraphs)):
                if full_para_text(paragraphs[j]).strip():
                    replace_whole_paragraph(paragraphs[j], tailoring["professional_summary"])
                    break
            break

    doc.save(dest_path)


def _apply_tailoring_to_cover_letter(source_path: Path, dest_path: Path, tailoring: dict, role_title: str) -> None:
    """Clone the template cover letter and apply role title + 4 paragraph substitutions."""
    import sys
    tool_dir = str(SAMRESUME_DIR / "_tools")
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    from docx_lib import (  # type: ignore
        Document,
        find_paragraph_containing,
        replace_whole_paragraph,
    )

    shutil.copy(source_path, dest_path)
    doc = Document(dest_path)

    # Role title line (typically "Partner Business Systems & AI Operations Lead" in template)
    for anchor in [
        "Partner Business Systems & AI Operations Lead",
        "Product Management, Research",
        "GTM Strategy",
    ]:
        p = find_paragraph_containing(doc, anchor)
        if p:
            replace_whole_paragraph(p, role_title)
            break

    # Replace the 4 body paragraphs by known anchors from v7_systems template
    paragraph_anchors = [
        ("Most of the work I've shipped for the last three years", tailoring["cover_letter_para_1"]),
        ("My starting point for all of this was a BI Engineer role", tailoring["cover_letter_para_2"]),
        ("Three specific reasons for Anthropic, specifically", tailoring["cover_letter_para_3"]),
        ("The conviction underneath all of this", tailoring["cover_letter_para_4"]),
    ]
    for anchor, new_text in paragraph_anchors:
        p = find_paragraph_containing(doc, anchor)
        if p:
            replace_whole_paragraph(p, new_text)

    doc.save(dest_path)


def _write_why_anthropic(output_dir: Path, tailoring: dict, role: dict, score_data: dict | None) -> Path:
    """Write the Why Anthropic free-form answer to a markdown file."""
    path = output_dir / "why_anthropic.md"
    header = f"# Why Anthropic — {role['title']}\n\n"
    header += f"For paste into the Anthropic application form's free-form 'Why Anthropic' field.\n"
    header += f"Target length: 200-400 words.\n"
    header += f"\n**Role URL:** {role['url']}\n"
    if score_data:
        header += f"**Match score:** {score_data.get('overall_score')} ({score_data.get('match_tier')})\n"
    header += "\n---\n\n"
    body = tailoring["why_anthropic"]
    path.write_text(header + body + "\n", encoding="utf-8")
    return path


def _write_metadata(output_dir: Path, role: dict, score_data: dict | None, tailoring: dict) -> Path:
    """Write metadata about how this package was generated."""
    meta = {
        "role_id": role.get("id"),
        "role_title": role.get("title"),
        "company": role.get("company"),
        "url": role.get("url"),
        "match_score": score_data.get("overall_score") if score_data else None,
        "match_tier": score_data.get("match_tier") if score_data else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tailoring_key_hooks": tailoring.get("key_role_hooks", []),
        "template_resume": TEMPLATE_RESUME.name,
        "template_cover_letter": TEMPLATE_COVER.name,
    }
    path = output_dir / "metadata.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_anthropic_package(role_id: str) -> dict:
    """Generate a full application package (resume + cover letter + Why Anthropic + metadata)
    for a Perfect Match Anthropic role.

    Output folder: /Users/Sam/Desktop/samresume/anthropic/perfect_matches/{slug}/

    Returns a dict describing the output files and key tailoring info.
    """
    supabase = get_supabase_client()
    profile = load_profile()

    # Fetch role
    result = supabase.table("roles").select("*").eq("id", role_id).execute()
    if not result.data:
        return {"status": "error", "reason": "role not found"}
    role = result.data[0]

    # Only handle Anthropic for now
    company_lower = (role.get("company") or "").lower().replace(" ", "")
    if "anthropic" not in company_lower:
        return {"status": "skipped", "reason": f"company not supported: {role['company']}"}

    # Don't generate for stale roles
    if role.get("is_live") is False:
        return {"status": "skipped", "reason": "role is stale (is_live=False)"}

    # Fetch score
    score_result = supabase.table("role_scores").select("*").eq("role_id", role_id).execute()
    score_data = score_result.data[0] if score_result.data else None

    # Gate: only tailor for Perfect Match roles
    if not score_data or score_data.get("overall_score", 0) < 90:
        return {"status": "skipped", "reason": "not a Perfect Match (score < 90)"}

    # Railway-safe guard: template files live on Sam's local machine.
    # If they're not accessible (e.g., this code is running on Railway), skip
    # gracefully. Packages get generated only when scoring runs locally.
    if not TEMPLATE_RESUME.exists() or not TEMPLATE_COVER.exists():
        logger.info(
            "Application tailor: template files not accessible (likely running in cloud env); "
            "skipping package generation"
        )
        return {
            "status": "skipped",
            "reason": "template files not accessible (cloud env)",
        }

    # Call Claude for tailoring JSON, then scrub for voice violations
    logger.info(f"Generating package for Anthropic role: {role['title']}")
    tailoring = _call_claude_for_tailoring(role, score_data, profile)
    tailoring = _scrub_tailoring(tailoring)

    # Create output folder
    slug = _slugify(role["title"])
    output_dir = OUTPUT_DIR / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write artifacts
    resume_path = output_dir / "resume.docx"
    _apply_tailoring_to_resume(TEMPLATE_RESUME, resume_path, tailoring)

    cover_path = output_dir / "cover_letter.docx"
    _apply_tailoring_to_cover_letter(TEMPLATE_COVER, cover_path, tailoring, role["title"])

    why_path = _write_why_anthropic(output_dir, tailoring, role, score_data)
    meta_path = _write_metadata(output_dir, role, score_data, tailoring)

    logger.info(f"Package generated at {output_dir}")
    return {
        "status": "generated",
        "role_id": role_id,
        "role_title": role["title"],
        "output_dir": str(output_dir),
        "files": {
            "resume": str(resume_path),
            "cover_letter": str(cover_path),
            "why_anthropic": str(why_path),
            "metadata": str(meta_path),
        },
        "tailoring_preview": {
            "subtitle": tailoring.get("subtitle"),
            "professional_summary": (tailoring.get("professional_summary") or "")[:180] + "...",
            "why_anthropic_preview": (tailoring.get("why_anthropic") or "")[:220] + "...",
            "key_role_hooks": tailoring.get("key_role_hooks", []),
        },
    }
