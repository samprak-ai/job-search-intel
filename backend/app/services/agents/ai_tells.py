"""AI-tell lexicon and structural heuristics.

Pure stdlib (no app.config, no network) so it is import-safe and runnable
offline (used by the deterministic layer of the reviewer and by selfcheck).

These catch the "sounds AI-written" failure mode Sam cares about: hype
adjectives, LLM-isms, dramatic openers, and structural tells. They are
ADVISORY by design (voice flags), not hard blocks. The hard-block list of
banned jargon stays in locked_facts.BANNED_PHRASES.
"""

from __future__ import annotations

import re

# --- Word/phrase lexicon (advisory voice flags) ---

# Hype adjectives/adverbs that read as marketing filler.
HYPE_WORDS = [
    "transformative", "revolutionary", "cutting-edge", "game-changing", "game changer",
    "world-class", "best-in-class", "robust", "seamless", "seamlessly", "unparalleled",
    "unprecedented", "powerful", "innovative", "dynamic", "vibrant", "bustling",
    "profoundly", "incredibly", "truly", "deeply passionate", "wealth of experience",
    "rich tapestry", "ever-evolving", "fast-paced", "next-level", "supercharge",
    "state-of-the-art", "groundbreaking", "stellar", "exceptional ability",
]

# LLM-ism verbs/nouns that flag generated prose.
LLM_ISMS = [
    "delve", "tapestry", "testament to", "boasts", "navigate the landscape",
    "underscore", "underscores", "showcase", "showcasing", "embark", "realm of",
    "foster", "pivotal", "harness", "elevate", "empower", "unlock", "spearhead",
    "spearheaded", "in the realm of", "at the forefront", "treasure trove",
    "it is worth noting", "notably", "furthermore", "moreover",
]

# Cliché openers / filler phrases.
CLICHE_OPENERS = [
    "in today's fast-paced", "in today's", "in the ever-evolving", "in the world of",
    "when it comes to", "at the end of the day", "needless to say",
    "it goes without saying", "i am thrilled", "i'm thrilled", "i am excited to",
    "i'm excited to", "i am writing to express", "i would be honored",
    "i am passionate about", "i'm passionate about", "as a seasoned",
    "with a proven track record",
]

# Combine the advisory lexicon with category labels.
LEXICON: dict[str, list[str]] = {
    "hype": HYPE_WORDS,
    "llm_ism": LLM_ISMS,
    "cliche": CLICHE_OPENERS,
}

# Structural tells (regex). Each tuple: (rule_name, compiled_pattern).
_NOT_ONLY = re.compile(r"\bnot only\b.*?\bbut also\b", re.IGNORECASE)
_NOT_JUST = re.compile(r"\bnot just\b[^.;,]*?,?\s*\bbut\b", re.IGNORECASE)
_ITS_NOT_X_ITS_Y = re.compile(r"\bit'?s not (just )?[^.;,]+,\s*it'?s\b", re.IGNORECASE)
# Tricolon: three comma-separated short items ending in "and" (overused parallelism).
_TRICOLON = re.compile(r"\b(\w+(?:\s\w+){0,3}),\s(\w+(?:\s\w+){0,3}),\sand\s(\w+(?:\s\w+){0,3})", re.IGNORECASE)

STRUCTURAL = [
    ("not_only_but_also", _NOT_ONLY),
    ("not_just_but", _NOT_JUST),
    ("its_not_x_its_y", _ITS_NOT_X_ITS_Y),
]


def _context(text: str, idx: int, span: int = 50) -> str:
    start = max(0, idx - span)
    end = min(len(text), idx + span)
    return text[start:end].replace("\n", " ").strip()


def _is_concrete_enumeration(m: re.Match) -> bool:
    """True if the tricolon is a factual list (proper nouns, acronyms, hyphenated
    names, or digits) rather than an abstract stylistic parallelism. We do NOT
    flag concrete enumerations like 'Cloud-Intel, Forge, and Job Search Intel'
    or 'internal metrics, CRM engagement, funding signals'."""
    for g in m.groups():
        if not g:
            continue
        body = g[1:]  # ignore a leading capital (could be sentence start)
        if any(c.isupper() for c in body) or any(c.isdigit() for c in g) or "-" in g:
            return True
    return False


def scan_ai_tells(text: str, *, tricolon_threshold: int = 3) -> list[dict]:
    """Return advisory voice flags found in `text`.

    Each flag: {category, rule, quote, confidence}. Deterministic and offline.
    Confidence: 'high' for lexicon + clear structural tells (these drive the
    reviewer verdict); 'low' for tricolons (noisy heuristic, info-only).
    Tricolons that are concrete factual enumerations are not flagged at all.
    """
    flags: list[dict] = []
    lower = text.lower()

    for category, terms in LEXICON.items():
        for term in terms:
            start = 0
            while True:
                idx = lower.find(term, start)
                if idx == -1:
                    break
                # "elevated to a/an <metric>" is factual usage, not an LLM-ism.
                if term == "elevate" and re.match(r"d?\s+to\s", lower[idx + len(term): idx + len(term) + 6]):
                    start = idx + len(term)
                    continue
                # "eval/test/fixture harness" is a real technical noun, not the
                # "harness the power of" LLM-ism.
                if term == "harness" and any(
                    w in lower[max(0, idx - 14): idx] for w in ("eval", "test", "fixture", "evaluation")
                ):
                    start = idx + len(term)
                    continue
                flags.append({
                    "category": category,
                    "rule": f"{category}: '{term}'",
                    "quote": _context(text, idx),
                    "confidence": "high",
                })
                start = idx + len(term)

    for rule, pattern in STRUCTURAL:
        for m in pattern.finditer(text):
            flags.append({
                "category": "structure",
                "rule": rule,
                "quote": _context(text, m.start()),
                "confidence": "high",
            })

    abstract_tricolons = [m for m in _TRICOLON.finditer(text)
                          if not _is_concrete_enumeration(m)]
    if len(abstract_tricolons) >= tricolon_threshold:
        for m in abstract_tricolons:
            flags.append({
                "category": "structure",
                "rule": "tricolon_overuse",
                "quote": _context(text, m.start()),
                "confidence": "low",
            })

    return flags


def ai_tell_density(text: str) -> float:
    """Flags per 100 words. Useful as a quick voice score input."""
    words = max(1, len(text.split()))
    return round(len(scan_ai_tells(text)) * 100.0 / words, 2)
