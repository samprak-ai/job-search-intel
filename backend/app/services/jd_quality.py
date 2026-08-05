"""JD quality gate — is this text actually a job description?

Motivating incident (2026-07-10): the Google Labs "Product GTM Strategy and
Operations" role scored 95 / Perfect Match against an EMPTY raw_jd. The scorer
reconstructed the role from its title, invented an incubation charter that the
real JD contradicts, and it became the top-ranked Google role. When the real JD
was supplied it scored 78 (Good Match) — a 17-point error.

Investigation showed the failure was NOT rare. `_parse_google_careers` in
ats_clients.py parses the search-RESULTS CARD, not the job detail page. A card
carries the title, the location, and the "Minimum qualifications" snippet, then
runs into page chrome ("Learn more share link Copy link"). 122 of 125
google_careers roles had no responsibilities section at all, and 49 of them
carried a Strong or Perfect score.

Two lessons are encoded here, both learned the hard way:

1. LENGTH IS NOT SUBSTANCE. The first guard drafted for this was
   `len(raw_jd) < 300 -> cap`. It would have passed the single worst row in the
   table: a LinkedIn scrape with 6,293 characters of benefits blurb, Fair Chance
   ordinance text, and application-window notices, and zero job content. Measure
   for the presence of job content, not the absence of shortness.

2. REQUIRE THE BODY, NOT THE HEADINGS. A checker for
   (responsibilities AND qualifications) false-positives on every Ashby posting
   (which says "About the Role" and never "qualifications") and every Amazon
   posting in the corpus. Meanwhile Google's cards DO carry "Minimum
   qualifications" — they are missing the *body*. The load-bearing signal is
   whether the text describes what the person would DO.
"""

from __future__ import annotations

import re

# Phrases that indicate the posting body — what the person actually does.
# Deliberately covers each ATS's house style:
#   Greenhouse/Workday -> "Responsibilities"
#   Ashby (OpenAI)     -> "About the Role" / "About the Team"
#   Amazon             -> "In this role you will" / "you'll"
#   Google Careers     -> "Responsibilities" (present ONLY on the detail page,
#                         absent from the results card)
_BODY_MARKERS = (
    r"responsibilit",
    r"in this role",
    r"you\s?will",
    r"you'?ll\b",
    r"what you'?ll do",
    r"about the role",
    r"about the team",
    r"day[-\s]to[-\s]day",
    r"what you'?ll be doing",
)

# Text that is legally/administratively mandated and carries no job signal.
# Present in bulk on LinkedIn scrapes. Used only for diagnostics.
_BOILERPLATE_MARKERS = (
    r"fair chance ordinance",
    r"application window will be open",
    r"qualified applications with arrest or conviction records",
    r"equal opportunity employer",
    r"e-verify",
    r"reasonable accommodation",
    r"benefits for this role include",
)

# Google Careers page chrome — proof the parser grabbed a card, not the JD.
_CHROME_MARKERS = (
    r"learn more share link",
    r"share link copy link",
    r"corporate_fare",
    r"bar_chart",
)

_MIN_BODY_CHARS = 200


def _matches(text: str, patterns: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [p for p in patterns if re.search(p, lowered)]


def boilerplate_ratio(raw_jd: str) -> float:
    """Rough share of the text that is legal/benefits boilerplate."""
    if not raw_jd:
        return 0.0
    hits = len(_matches(raw_jd, _BOILERPLATE_MARKERS))
    return min(1.0, hits / 3.0)


def is_substantive_jd(raw_jd: str | None) -> bool:
    """True when the text plausibly describes the job itself.

    Substantive means: non-trivial length AND at least one body marker
    describing what the person would do. Qualifications alone do not qualify —
    that is exactly the shape of a Google Careers results card.
    """
    return not jd_quality_reason(raw_jd)


def jd_quality_reason(raw_jd: str | None) -> str | None:
    """Return None when the JD is substantive, else a short reason string.

    The reason is surfaced to the scorer as a gap and logged as a detected_gap,
    so a thin JD is visible rather than silently reconstructed from the title.
    """
    if raw_jd is None or not raw_jd.strip():
        return "raw_jd is empty"

    text = raw_jd.strip()

    if len(text) < _MIN_BODY_CHARS:
        return f"raw_jd is only {len(text)} chars (min {_MIN_BODY_CHARS})"

    if _matches(text, _CHROME_MARKERS) and not _matches(text, _BODY_MARKERS):
        return (
            "raw_jd looks like a Google Careers search-results card "
            "(page chrome present, no responsibilities body)"
        )

    if not _matches(text, _BODY_MARKERS):
        if _matches(text, _BOILERPLATE_MARKERS):
            return (
                f"raw_jd is {len(text)} chars of legal/benefits boilerplate "
                "with no job-content section"
            )
        return "raw_jd has no responsibilities / about-the-role body"

    return None


# --- Cap policy ----------------------------------------------------------
# A role whose JD we cannot verify must not be asserted as a top match.
# 79 sits one point under the Strong Match floor (80), which is also the
# non-Amazon notification bar — so an unverified role stays visible on the
# dashboard but never emails, never enters the digest, and never becomes a
# Friday recommendation.
UNVERIFIED_JD_SCORE_CAP = 79
UNVERIFIED_JD_TIER_CAP = "Good Match"

# Reason-aware cap (2026-08-05): a Google Careers search CARD is not empty — it
# carries title + location + level + "Minimum qualifications", which is
# substantive enough to assert a Strong match (Sam's convertible archetypes —
# Strategy & Ops, GTM Specialist — were being false-capped to Good). It only
# lacks the responsibilities BODY needed to confirm Perfect. So Google cards cap
# at the Strong ceiling (88), not Good; the catastrophic error the gate was built
# for (a false PERFECT, 95->78) is still blocked. Empty/boilerplate JDs, which
# carry no verifiable content, still cap to 79/Good.
GOOGLE_CARD_SCORE_CAP = 88
_GOOGLE_CARD_MARKER = "Google Careers search-results card"


def _tier_for_score(score: int) -> str:
    if score >= 90:
        return "Perfect Match"
    if score >= 80:
        return "Strong Match"
    if score >= 70:
        return "Good Match"
    if score >= 60:
        return "Possible Match"
    return "Unlikely Match"


def apply_jd_quality_cap(score_data: dict, raw_jd: str | None) -> dict:
    """Cap a score when the JD it was derived from is not substantive.

    Mutates and returns score_data. Idempotent.
    """
    reason = jd_quality_reason(raw_jd)
    if reason is None:
        return score_data

    is_google_card = _GOOGLE_CARD_MARKER in reason
    cap = GOOGLE_CARD_SCORE_CAP if is_google_card else UNVERIFIED_JD_SCORE_CAP

    original = score_data.get("overall_score", 0)
    if original > cap:
        score_data["overall_score"] = cap
        score_data["match_tier"] = _tier_for_score(cap)
        score_data["rationale"] = (
            f"[JD QUALITY CAP: scored {original}, capped to {cap}] "
            f"{score_data.get('rationale', '')}"
        )

    tail = " full JD needed to confirm Perfect-tier." if is_google_card else " until the JD is refetched."
    gap = f"Unverified JD ({reason}) — score is capped;{tail}"
    gaps = score_data.setdefault("gaps", [])
    if gap not in gaps:
        gaps.insert(0, gap)

    return score_data
