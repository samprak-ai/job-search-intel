"""Stage 6: Critic.

Adversarial verification of the drafter's output. The critic is explicitly
told its job is to FAIL the package — find every claim not grounded in the
persona / locked-in facts / JD, every tone violation, every length miss.

Returns structured findings JSON across six categories. Empty arrays only if
the critic genuinely found nothing after careful review.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import anthropic
from datetime import date
from docx import Document

from app.config import get_settings
from app.services.agents.locked_facts import BANNED_CHARS, BANNED_PHRASES

logger = logging.getLogger(__name__)


CRITIC_SYSTEM_PROMPT = """You are an adversarial reviewer for Sam Prakash's job application packages.

YOUR JOB IS TO FAIL THIS PACKAGE. Your bias is toward finding issues, not approving.

You receive:
1. Sam's persona (profile.json, interview narrative, locked-in facts)
2. The role's full JD
3. The requirements spec (length targets, tone rules, must-include, must-not-claim)
4. The selected angles for this role
5. The three artifacts: resume text, cover letter text, why_anthropic text

GROUND TRUTH: The locked-in facts in Sam's persona are non-negotiable, verified statements about
his real work. Do NOT challenge them or treat them as "future dates" or "speculative." If a
claim appears verbatim or is consistent with the locked-in facts, it is grounded — do not flag it.

For each artifact, find every:
- HALLUCINATION: claim with no evidence in persona/narrative/locked-in facts. Example: "I led a team of 12" when persona shows no team-lead role.
- UNSUPPORTED_CLAIM: claim that needs a citation/quantification but doesn't have one in source. Example: "improved revenue by 30%" when no 30% figure exists.
- FACTUAL_ERROR: claim that contradicts source. Example: "12+ years at AWS" when source says "6.5+ at AWS, 12+ total." Or a number that doesn't match the locked-in facts exactly (e.g., "65% reduction" instead of "70% reduction").
- TONE_VIOLATION: banned jargon phrases ONLY ("uniquely positioned", "mission-critical", "synergy", "transformative", "passionate about", "cross-functional alignment", "drive outcomes", "scale initiatives"), and any other overt marketing-speak.
  DO NOT flag em dashes, en dashes, or the interpunct separator (·) — those are checked separately via deterministic rules before this review, not your job.
  DO NOT flag year-range date separators (e.g. "2022–Present", "2019–2022") — correct formatting.
  DO NOT flag header lines like "# Why Anthropic — Role Title" — that is a template label, not authored content.
  If you flag a dash-related or interpunct issue, that finding will be automatically discarded.
- LENGTH_VIOLATION: artifact body word count falls outside spec target range.
- ROLE_FIT_DRIFT: claim that drifts from the role's actual JD hooks or the selected angles.

For each finding, cite the EXACT quote (verbatim from the artifact). If you cannot quote it, you do not have a finding. Keep quotes under 150 characters. Replace embedded newlines in quotes with a single space.

If you find nothing in a category, return an empty array for that category. Empty everywhere is acceptable when the artifacts are genuinely clean — do not invent findings.

CRITICAL JSON FORMATTING: Output a single valid JSON object. Inside string values, do NOT use literal newlines, tabs, or other control characters — replace them with spaces. Do not include backticks or markdown fencing.

Output JSON ONLY in this exact shape:
{
  "hallucinations": [
    {"artifact": "resume|cover_letter|why_anthropic", "claim": "...", "quote": "...", "why_no_evidence": "..."}
  ],
  "unsupported_claims": [
    {"artifact": "...", "claim": "...", "quote": "..."}
  ],
  "factual_errors": [
    {"artifact": "...", "claim": "...", "quote": "...", "correct_value": "...", "source": "..."}
  ],
  "tone_violations": [
    {"artifact": "...", "rule": "...", "quote": "..."}
  ],
  "length_violations": [
    {"artifact": "...", "target": "...", "actual": "..."}
  ],
  "role_fit_drift": [
    {"artifact": "...", "claim": "...", "quote": "...", "why_off_target": "..."}
  ]
}"""


def _parse_lenient_json(text: str) -> dict:
    """Parse JSON tolerant of control chars (newlines/tabs) inside string values.

    Claude sometimes embeds literal newlines inside quoted strings when echoing
    multi-line source content. Standard json.loads rejects this, but the
    strict=False decoder accepts it. If even that fails, do a last-ditch
    escape pass on raw control chars and retry.
    """
    decoder = json.JSONDecoder(strict=False)
    try:
        return decoder.decode(text)
    except json.JSONDecodeError:
        # Last-ditch: escape any unescaped control chars that survived
        import re
        # Replace literal newlines/tabs/etc. inside the buffer with their escape sequences.
        # This is approximate but usually salvages Claude's output.
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        cleaned = cleaned.replace("\r\n", "\\n").replace("\n", "\\n").replace("\t", "\\t")
        return decoder.decode(cleaned)


def _extract_docx_text(path: str | Path) -> str:
    """Read a .docx file into newline-joined paragraph text."""
    p = Path(path)
    if not p.exists():
        return f"(file not found: {p})"
    try:
        doc = Document(str(p))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except Exception as e:
        logger.warning(f"Could not extract docx text from {p}: {e}")
        return f"(error reading {p}: {e})"


def _read_text_file(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return f"(file not found: {p})"
    return p.read_text(encoding="utf-8")


def _deterministic_pre_checks(
    resume_text: str,
    cover_text: str,
    why_text: str,
    requirements: dict,
) -> dict:
    """Cheap, deterministic findings the LLM should not have to discover.

    Currently catches: em/en dashes, banned phrases, length misses on
    cover-letter and why-anthropic bodies. Resume page-count is hard to
    measure from text alone; we leave that to manual eyeball or the LLM.
    """
    findings: dict[str, list[dict]] = {
        "tone_violations": [],
        "length_violations": [],
    }

    artifacts = {
        "resume": resume_text,
        "cover_letter": cover_text,
        "why_anthropic": why_text,
    }

    # Tone: banned characters
    # Two exemptions from the banned-char check:
    #  1. Year-range date separators in the resume (e.g. "2022–Present",
    #     "2019–2022") — Word auto-formats these; they aren't author choices.
    #  2. The markdown header line in why_anthropic (e.g. "# Why Anthropic —
    #     Role Title") — that's a template label, not body content we write.
    _year_range_re = re.compile(r"\d{4}[–—](?:\d{4}|Present|present)")

    for artifact, raw_text in artifacts.items():
        # For why_anthropic, strip the header block before char checks
        check_text = raw_text
        if artifact == "why_anthropic":
            for sep in ["\n\n", "\n---\n", "---\n"]:
                if sep in check_text:
                    check_text = check_text.split(sep, 1)[1]
                    break
            else:
                check_text = check_text.split("\n", 1)[-1]

        for ch in BANNED_CHARS:
            if ch not in check_text:
                continue
            pos = 0
            while True:
                idx = check_text.find(ch, pos)
                if idx == -1:
                    break
                context = check_text[max(0, idx - 5): idx + 10]
                if _year_range_re.search(context):
                    pos = idx + 1
                    continue  # date-range separator, not a tone violation
                start = max(0, idx - 60)
                end = min(len(check_text), idx + 60)
                quote = check_text[start:end].replace("\n", " ").strip()
                findings["tone_violations"].append(
                    {
                        "artifact": artifact,
                        "rule": f"banned character '{ch}' (em/en dash)",
                        "quote": quote,
                    }
                )
                pos = idx + 1

    # Tone: banned phrases
    for artifact, text in artifacts.items():
        lower = text.lower()
        for phrase in BANNED_PHRASES:
            if phrase in lower:
                idx = lower.find(phrase)
                start = max(0, idx - 40)
                end = min(len(text), idx + len(phrase) + 40)
                quote = text[start:end].replace("\n", " ").strip()
                findings["tone_violations"].append(
                    {
                        "artifact": artifact,
                        "rule": f"banned phrase '{phrase}'",
                        "quote": quote,
                    }
                )

    # Length: cover letter body and why-anthropic body
    targets = requirements.get("length_targets") or {}
    cover_min, cover_max = targets.get("cover_letter_body", (0, 99999))
    why_min, why_max = targets.get("why_anthropic_body", (0, 99999))

    cover_words = len(cover_text.split())
    if cover_words < cover_min or cover_words > cover_max:
        findings["length_violations"].append(
            {
                "artifact": "cover_letter",
                "target": f"{cover_min}-{cover_max} words",
                "actual": f"{cover_words} words",
            }
        )

    # why_anthropic.md has a header followed by '---' then the body. Count body words only.
    body = why_text
    if "---" in body:
        body = body.split("---", 2)[-1]
    body_words = len(re.sub(r"\*\*|\*", "", body).split())
    if body_words < why_min or body_words > why_max:
        findings["length_violations"].append(
            {
                "artifact": "why_anthropic",
                "target": f"{why_min}-{why_max} words",
                "actual": f"{body_words} words",
            }
        )

    return findings


async def critique(
    role: dict,
    persona: dict,
    artifact_paths: dict,
    requirements: dict,
    angles: list[dict],
) -> dict:
    """Run the critic. Returns findings dict with 6 categories."""
    # Read artifacts into text
    resume_text = _extract_docx_text(artifact_paths.get("resume", ""))
    cover_text = _extract_docx_text(artifact_paths.get("cover_letter", ""))
    why_text = _read_text_file(artifact_paths.get("why_anthropic", ""))

    # Cheap deterministic checks first — these are easier than asking the LLM
    deterministic = _deterministic_pre_checks(resume_text, cover_text, why_text, requirements)

    # LLM critic call
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    persona_block = json.dumps(
        {
            "profile_json": persona["profile_json"],
            "locked_in_facts": persona["locked_in_facts"],
        },
        indent=2,
    )
    narrative = persona["interview_narrative"][:8000]

    today = date.today().isoformat()
    user_msg = f"""## Today's date
{today}

## Sam's persona
{persona_block}

## Sam's interview narrative
{narrative}

## Role
**Title:** {role['title']}
**Company:** {role.get('company', 'Anthropic')}

**JD:**
{role.get('raw_jd', '(no JD)')[:8000]}

## Requirements spec
{json.dumps(requirements, indent=2)}

## Selected angles for this role
{json.dumps(angles, indent=2)}

## Artifacts to review

=== RESUME (extracted text) ===
{resume_text}

=== COVER LETTER (extracted text) ===
{cover_text}

=== WHY ANTHROPIC (markdown source) ===
{why_text}

Find every issue. Cite exact quotes. Output JSON only."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=CRITIC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        llm_findings = _parse_lenient_json(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Critic returned invalid JSON: {response_text[:500]}")
        raise ValueError(f"Critic JSON parse failed: {e}")

    # Merge: deterministic findings PLUS LLM findings (LLM tone/length may dupe deterministic)
    findings = {
        "hallucinations": llm_findings.get("hallucinations") or [],
        "unsupported_claims": llm_findings.get("unsupported_claims") or [],
        "factual_errors": llm_findings.get("factual_errors") or [],
        "tone_violations": (deterministic["tone_violations"] + (llm_findings.get("tone_violations") or [])),
        "length_violations": (deterministic["length_violations"] + (llm_findings.get("length_violations") or [])),
        "role_fit_drift": llm_findings.get("role_fit_drift") or [],
    }

    total = sum(len(v) for v in findings.values())
    logger.info(
        f"Critic pass for {role.get('title')}: {total} findings "
        f"({len(findings['hallucinations'])} hallucinations, "
        f"{len(findings['unsupported_claims'])} unsupported, "
        f"{len(findings['factual_errors'])} factual errors, "
        f"{len(findings['tone_violations'])} tone, "
        f"{len(findings['length_violations'])} length, "
        f"{len(findings['role_fit_drift'])} fit drift)"
    )
    return findings


def has_findings(findings: dict) -> bool:
    """True if any finding category is non-empty."""
    return any(findings.get(k) for k in (
        "hallucinations", "unsupported_claims", "factual_errors",
        "tone_violations", "length_violations", "role_fit_drift",
    ))


def count_findings(findings: dict) -> int:
    return sum(len(findings.get(k) or []) for k in (
        "hallucinations", "unsupported_claims", "factual_errors",
        "tone_violations", "length_violations", "role_fit_drift",
    ))
