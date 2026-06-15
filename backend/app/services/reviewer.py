"""Application Reviewer — company-agnostic QC for any drafted application text.

Complements the Anthropic-only agents/critic.py pipeline. Where the critic runs
inside the docx packaging flow for Anthropic, this reviewer grades ANY text for
ANY company (OpenAI Additional Info, DeepMind cover letters, Amazon internal
packets, etc.) and is exposed via POST /review.

Four graders, mapped to Sam's stated concerns:
  1. format      (deterministic) - banned chars/phrases, length, contact line
  2. ai_tells    (deterministic) - sweeping/dramatic/LLM-ish voice flags  [#1]
  3. voice       (LLM, advisory)  - similarity to Sam's real writing        [#3]
  4. groundedness(LLM, HARD BLOCK)- every claim traceable to persona        [#2]
  5. alignment   (LLM, advisory)  - addresses company values + role demands

Gate policy (Sam's choice): HARD BLOCK on groundedness only. Everything else is
advisory (surfaced as must-fix for objective format misses, flags otherwise).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from app.services.agents.ai_tells import scan_ai_tells, ai_tell_density
from app.services.agents.locked_facts import BANNED_PHRASES, BANNED_CHARS

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"  # match the model the app already uses in prod

# ---------------------------------------------------------------------------
# Company / artifact specs
# ---------------------------------------------------------------------------
# (min, max) word counts per artifact type, by company. Sourced from CLAUDE.md
# + per-company application research.
COMPANY_SPECS: dict[str, dict[str, Any]] = {
    "Anthropic": {
        "length": {"why": (200, 400), "cover_letter": (350, 550)},
        "values": "AI safety, reliability, interpretability, steerability; high agency; "
                  "truth-seeking; pragmatism; doing the simple thing that works; mission over hype.",
    },
    "OpenAI": {
        "length": {"additional_info": (150, 350), "cover_letter": (250, 450)},
        "values": "scaling safe AGI to benefit humanity; intensity and speed; building things "
                  "that ship; iteration; concrete impact over credentials.",
    },
    "Google DeepMind": {
        "length": {"cover_letter": (200, 400)},
        "values": "frontier research translated to products; scientific rigor; responsibility "
                  "and safety; ambitious, careful engineering.",
    },
    "Google": {
        "length": {"cover_letter": (200, 400)},
        "values": "user focus, scale, technical excellence, responsible AI.",
    },
    "Amazon": {
        "length": {"why_role": (60, 250), "relevant_skills": (60, 250),
                   "performance_history": (40, 150), "work_contribution": (40, 130)},
        "values": "Leadership Principles: Customer Obsession, Ownership, Invent and Simplify, "
                  "Dive Deep, Bias for Action, Deliver Results, Earn Trust, Think Big.",
    },
}

CONTACT_PHONE = "602-596-2974"

# Amazon writing-style weasel words (vague qualifiers Amazon explicitly discourages).
AMAZON_WEASEL = [
    "roughly", "approximately", "around", "various", "a variety of", "significantly",
    "several", "numerous", "a number of", "a lot of", "fairly", "quite", "somewhat",
    "hopefully", "should help", "helps to", "aim to", "many", "lots of",
]

# Year-range separators (e.g. "2022–Present", "2019–2022") are Word auto-format,
# not authored em-dash choices. Exempt them from the banned-char check (parity
# with agents/critic._deterministic_pre_checks).
_YEAR_RANGE = re.compile(r"\d{4}[–—](?:\d{4}|Present|present)")


def get_company_spec(company: str | None) -> dict:
    return COMPANY_SPECS.get((company or "").strip(), {"length": {}, "values": ""})


# ---------------------------------------------------------------------------
# Deterministic graders (offline, no API key)
# ---------------------------------------------------------------------------
def deterministic_review(
    text: str,
    *,
    company: str | None = None,
    artifact_type: str | None = None,
    require_contact: bool = False,
) -> dict:
    """Format + AI-tell checks. Pure stdlib. Returns format + ai_tells grader dicts."""
    fmt_flags: list[dict] = []

    # Banned characters (em/en dash), exempting year-range date separators.
    for ch in BANNED_CHARS:
        idx = text.find(ch)
        while idx != -1:
            ctx = text[max(0, idx - 5): idx + 10]
            if _YEAR_RANGE.search(ctx):
                idx = text.find(ch, idx + 1)
                continue
            start, end = max(0, idx - 40), min(len(text), idx + 40)
            fmt_flags.append({
                "rule": f"banned character '{ch}' (em/en dash)",
                "quote": text[start:end].replace("\n", " ").strip(),
                "must_fix": True,
            })
            idx = text.find(ch, idx + 1)

    # Banned jargon phrases (the hard-jargon list)
    lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            idx = lower.find(phrase)
            start, end = max(0, idx - 30), min(len(text), idx + len(phrase) + 30)
            fmt_flags.append({
                "rule": f"banned phrase '{phrase}'",
                "quote": text[start:end].replace("\n", " ").strip(),
                "must_fix": True,
            })

    # Length vs spec
    spec = get_company_spec(company)
    words = len(re.sub(r"\*\*|\*", "", text).split())
    bounds = (spec.get("length") or {}).get(artifact_type or "", None)
    if bounds:
        lo, hi = bounds
        if words < lo or words > hi:
            fmt_flags.append({
                "rule": f"length out of range for {company}/{artifact_type}",
                "quote": f"{words} words (target {lo}-{hi})",
                "must_fix": True,
            })

    # Contact line (resume / cover letter only)
    if require_contact and CONTACT_PHONE not in text:
        fmt_flags.append({
            "rule": "missing contact line",
            "quote": f"expected phone {CONTACT_PHONE}",
            "must_fix": True,
        })

    # Claim guards (accuracy).
    # (a) "12+ years" must be qualified as total experience, not GTM/strategy/at-AWS.
    for m in re.finditer(r"12\+?\s*y(?:ea)?rs?", text, re.IGNORECASE):
        tail = text[m.end(): m.end() + 24].lower()
        if "total" in tail or "experience" in tail:
            continue
        s, e = max(0, m.start() - 8), min(len(text), m.end() + 34)
        fmt_flags.append({
            "rule": "overclaim: '12+ years' must be qualified as total experience (not GTM/Strategy/Sales Ops/at-AWS)",
            "quote": text[s:e].replace("\n", " ").strip(),
            "must_fix": True,
        })
    # (b) LinkedIn cited as a data/discovery source is restricted for AI tools.
    for m in re.finditer(r"LinkedIn", text):
        s, e = max(0, m.start() - 30), min(len(text), m.end() + 12)
        fmt_flags.append({
            "rule": "LinkedIn cited as a source (restricted for AI tools) - remove or verify",
            "quote": text[s:e].replace("\n", " ").strip(),
            "must_fix": False,
        })

    # (c) Amazon writing style (Amazon artifacts only): weasel words + we/our in self-assessment.
    if (company or "").strip() == "Amazon":
        for w in AMAZON_WEASEL:
            for m in re.finditer(r"\b" + re.escape(w) + r"\b", text, re.IGNORECASE):
                fmt_flags.append({
                    "rule": f"Amazon style: weasel word '{w}' - be specific / quantify",
                    "quote": text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ").strip(),
                    "must_fix": False,
                })
        for m in re.finditer(r"\b(?:we|our|us)\b", text, re.IGNORECASE):
            fmt_flags.append({
                "rule": "Amazon style: prefer 'I' over 'we/our' in self-assessment",
                "quote": text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ").strip(),
                "must_fix": False,
            })

    # (d) AI-product framing: lead with substance, not the tool.
    for m in re.finditer(r"\bbuil[td][^.]{0,12}\b(?:with|using|on)\s+claude code\b", text, re.IGNORECASE):
        fmt_flags.append({
            "rule": "AI-products framing: lead with the engineering substance, not 'built with Claude Code'",
            "quote": text[max(0, m.start() - 20): m.end() + 20].replace("\n", " ").strip(),
            "must_fix": False,
        })
    # Non-engineer angle is AI-labs-only: drop it from Amazon artifacts.
    if (company or "").strip() == "Amazon":
        for phrase in ["without a traditional", "non-engineer", "without a formal engineering"]:
            idx = text.lower().find(phrase)
            if idx != -1:
                fmt_flags.append({
                    "rule": "Amazon: drop the non-engineer / no-formal-background angle (AI-labs only)",
                    "quote": text[max(0, idx - 25): idx + 35].replace("\n", " ").strip(),
                    "must_fix": True,
                })

    # (e) Amazon-internal performance language must NOT appear on external (non-Amazon) artifacts.
    #     "Exceeds High Bar" / "annual review" etc. are insider rating vocabulary that means nothing
    #     to an external reviewer and signals internal-review copy-paste. Keep them for Amazon only.
    _company = (company or "").strip()
    _is_external = bool(_company) and _company != "Amazon"
    for term in ("exceeds high bar", "annual review", "annual performance rating",
                 "forte goals", "promo doc"):
        idx = text.lower().find(term)
        if idx != -1 and _company != "Amazon":
            fmt_flags.append({
                "rule": "Amazon-internal performance language on a non-Amazon artifact - remove (Amazon-only detail)",
                "quote": text[max(0, idx - 25): idx + 35].replace("\n", " ").strip(),
                "must_fix": _is_external,
            })

    tells = scan_ai_tells(text)
    high = [f for f in tells if f.get("confidence") != "low"]
    return {
        "format": {"flags": fmt_flags, "must_fix": any(f.get("must_fix") for f in fmt_flags),
                   "word_count": words},
        "ai_tells": {"flags": tells, "density_per_100w": ai_tell_density(text),
                     "count": len(tells), "high_confidence_count": len(high)},
    }


# ---------------------------------------------------------------------------
# Voice samples (Sam's real writing) — from sam-profile.md blockquotes
# ---------------------------------------------------------------------------
def _sam_profile_path() -> Path:
    # Host path (deployed). The reviewer reads the interview narrative for voice.
    for p in (
        Path("/Users/Sam/Desktop/samresume/_context/sam-profile.md"),
        Path("/sessions/ecstatic-upbeat-cerf/mnt/samresume/_context/sam-profile.md"),
    ):
        if p.exists():
            return p
    return Path("/Users/Sam/Desktop/samresume/_context/sam-profile.md")


def load_voice_samples(max_samples: int = 8) -> list[str]:
    """Extract Sam's verbatim interview answers (markdown blockquotes) as voice ground truth."""
    path = _sam_profile_path()
    if not path.exists():
        return []
    samples: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(">") and len(s) > 40:
            samples.append(s.lstrip("> ").strip())
    return samples[:max_samples]


# ---------------------------------------------------------------------------
# LLM graders
# ---------------------------------------------------------------------------
def _client():
    import anthropic  # lazy
    from app.config import get_settings
    return anthropic.Anthropic(api_key=get_settings().anthropic_api_key)


def _call_json(system: str, user: str, max_tokens: int = 1500) -> dict:
    client = _client()
    resp = client.messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {"error": "unparseable", "raw": raw[:500]}


GROUNDEDNESS_SYSTEM = """You are an adversarial fact-checker for Sam Prakash's job application text.
Your job is to FAIL any claim not grounded in his persona / locked-in facts / resume.

You receive Sam's persona (profile.json + locked-in facts + interview narrative) and a draft.
GROUND TRUTH: the locked-in facts are verified, non-negotiable. Do NOT challenge them or treat
them as speculative/future-dated. A claim consistent with them is grounded.

Flag every:
- HALLUCINATION: a claim with no support in the persona (e.g., "I led a team of 12" with no such role).
- UNSUPPORTED: a claim needing a number/citation that the persona does not contain.
- FACTUAL_ERROR: a claim that contradicts the persona (e.g., "12+ years at AWS" vs "6.5+ at AWS, 12+ total"; wrong metric).
Cite the EXACT verbatim quote (<150 chars). If you cannot quote it, it is not a finding.
Output JSON ONLY: {"unsupported":[{"type":"hallucination|unsupported|factual_error","quote":"...","why":"...","fix":"suggested grounded rewrite or removal"}], "score": 0-100}
score = groundedness (100 = every claim fully supported)."""

VOICE_SYSTEM = """You judge whether a draft sounds like Sam Prakash, using SAMPLES of his real writing.
Sam's voice: plain, direct, concrete, first-person, no hype, no marketing jargon, no sweeping
claims. He hates clichés and sophistication that exceeds meaning.
Given his real samples and a draft, score voice similarity and flag the lines that read unlike him
(too polished, dramatic, generic, or AI-generated).
Output JSON ONLY: {"score":0-100, "flags":[{"quote":"...","why":"reads unlike Sam","fix":"plainer rewrite"}], "summary":"one sentence"}"""

ALIGNMENT_SYSTEM = """You judge whether a draft addresses what the COMPANY values and what the ROLE demands.
You receive: the company's values, the role JD (or title), and the draft.
Flag generic enthusiasm that could apply to any company, and claims that miss the role's real bar.
Reward concrete, role-specific, values-aligned points grounded in the candidate's evidence.
Output JSON ONLY: {"score":0-100, "flags":[{"quote":"...","issue":"generic|misses-bar|off-values","fix":"..."}], "summary":"one sentence"}"""


def grade_groundedness(text: str, persona: dict) -> dict:
    persona_block = json.dumps({
        "profile_json": persona.get("profile_json"),
        "locked_in_facts": persona.get("locked_in_facts"),
        "interview_narrative": (persona.get("interview_narrative") or "")[:6000],
    }, ensure_ascii=False)[:18000]
    user = f"PERSONA:\n{persona_block}\n\nDRAFT:\n{text}"
    out = _call_json(GROUNDEDNESS_SYSTEM, user)
    out["blocking"] = bool(out.get("unsupported"))
    return out


def grade_voice(text: str, samples: list[str]) -> dict:
    sample_block = "\n---\n".join(samples) if samples else "(no samples available)"
    user = f"SAM'S REAL WRITING SAMPLES:\n{sample_block}\n\nDRAFT:\n{text}"
    return _call_json(VOICE_SYSTEM, user)


def grade_alignment(text: str, company: str | None, jd: str | None) -> dict:
    spec = get_company_spec(company)
    user = (f"COMPANY: {company}\nCOMPANY VALUES: {spec.get('values','')}\n\n"
            f"ROLE JD / TITLE:\n{(jd or '(not provided)')[:6000]}\n\nDRAFT:\n{text}")
    return _call_json(ALIGNMENT_SYSTEM, user)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def review(
    text: str,
    *,
    company: str | None = None,
    artifact_type: str | None = None,
    jd: str | None = None,
    require_contact: bool = False,
    use_llm: bool = True,
) -> dict:
    """Run all graders and assemble a verdict.

    Verdict policy: BLOCK iff groundedness finds any unsupported claim. Otherwise
    REVIEW if any must-fix format miss or advisory flags exist, else PASS.
    """
    report: dict[str, Any] = {
        "company": company,
        "artifact_type": artifact_type,
        "graders": {},
        "scores": {},
        "llm_used": False,
        "blocking_reasons": [],
    }

    det = deterministic_review(text, company=company, artifact_type=artifact_type,
                               require_contact=require_contact)
    report["graders"].update(det)

    if use_llm:
        try:
            from app.services.agents.persona_loader import load_persona
            persona = load_persona()
            g = grade_groundedness(text, persona)
            report["graders"]["groundedness"] = g
            report["scores"]["groundedness"] = g.get("score")
            v = grade_voice(text, load_voice_samples())
            report["graders"]["voice"] = v
            report["scores"]["voice"] = v.get("score")
            a = grade_alignment(text, company, jd)
            report["graders"]["alignment"] = a
            report["scores"]["alignment"] = a.get("score")
            report["llm_used"] = True
            if g.get("blocking"):
                report["blocking_reasons"].append("groundedness: unsupported claim(s) present")
        except Exception as e:  # API key missing or call failed — degrade to deterministic
            logger.warning(f"LLM graders unavailable, deterministic-only: {e}")
            report["llm_error"] = str(e)

    # Verdict
    if report["blocking_reasons"]:
        report["verdict"] = "block"
    elif det["format"]["must_fix"] or det["ai_tells"]["high_confidence_count"] > 0 or any(
        report["graders"].get(k, {}).get("flags") for k in ("voice", "alignment")
    ):
        report["verdict"] = "review"
    else:
        report["verdict"] = "pass"
    return report
