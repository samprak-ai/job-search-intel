"""Stage 1: Gate.

Deterministic skip-or-proceed check before any Claude call. Hard rejects:
  - role is stale (is_live=False)
  - title pattern is engineer/SA (defense-in-depth; scoring already filters)
  - role not at Anthropic (this pipeline is Anthropic-only for now)
  - already-packaged (handled by the orchestrator via DB lookup, not here)

Word lists ported from the legacy `application_packets.py` exploration.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Hard-exclude title patterns. If any of these appear in the title (case-insensitive),
# we never package the role — these are the roles Sam has explicitly said he is not
# pursuing (engineer / SA tracks).
HARD_EXCLUDE_TITLE_SIGNALS = [
    "solutions engineer",
    "solution engineer",
    "solutions architect",
    "solution architect",
    "sales engineer",
    "customer engineer",
    "forward deployed engineer",
    "partner engineer",
    "engineering manager",
    "applied ai engineering",
]

# Generic engineering catch — last-resort filter after the specific phrases above.
GENERIC_ENGINEER_SIGNALS = [" engineer", "engineering "]

# Non-US location signals. If the role lists a non-US location AND does not mention
# US/remote, we skip. (Sam's H1B status makes remote-US-or-bust the constraint.)
NON_US_SIGNALS = [
    "paris",
    "sweden",
    "morocco",
    "emea",
    "london",
    "united kingdom",
    "dublin",
    "ireland",
    "tokyo",
    "japan",
    "singapore",
    "seoul",
    "korea",
    "canada",
    "toronto",
    "vancouver",
    "australia",
    "india",
]

US_OK_SIGNALS = ["remote", "united states", " us ", " us,", " us.", "u.s.", "usa", "new york", "san francisco", "seattle"]


def _norm(value: str | None) -> str:
    return (value or "").lower().strip()


def gate_check(role: dict) -> Optional[str]:
    """Return a skip-reason string if the role should be skipped, else None.

    Caller is responsible for checking 'already packaged' via DB — gate_check
    is deterministic and stateless w.r.t. the application_packages table.
    """
    title = _norm(role.get("title"))
    company = _norm(role.get("company")).replace(" ", "")
    raw_jd = _norm(role.get("raw_jd"))[:3000]
    department = _norm(role.get("department"))
    url = _norm(role.get("url"))
    location_text = f"{title} {department} {url} {raw_jd}"

    # Anthropic-only for v1
    if company != "anthropic":
        return f"not_anthropic ({company})"

    # Stale
    if role.get("is_live") is False:
        return "stale_posting"

    # Engineer / SA hard exclusions
    for signal in HARD_EXCLUDE_TITLE_SIGNALS:
        if signal in title:
            return f"engineer_or_sa_track:{signal}"

    for signal in GENERIC_ENGINEER_SIGNALS:
        if signal in f" {title} ":
            return f"generic_engineer_title:{signal.strip()}"

    # Non-US without US-OK signal
    if any(s in location_text for s in NON_US_SIGNALS):
        if not any(s in location_text for s in US_OK_SIGNALS):
            return "non_us_location"

    return None
