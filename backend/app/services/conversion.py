"""Conversion axis — how likely Sam gets a CALLBACK given his background, kept
SEPARATE from the fit score.

Sam's background is 12+ years GTM / Sales-Ops / business-strategy at AWS Startups
plus hands-on AI building (GenAI-Intel, Forge, Proactive Intelligence Pillar) —
NOT a traditional product-management career. So a role's *fit* (how well it
matches his skills — lives in role_scores.overall_score) and his *conversion
likelihood* (will a recruiter call given his resume shape) are DIFFERENT axes.
Baking conversion into the fit score made the LLM scorer inconsistent (it
under-tempered generic PM and over-tempered a convertible role), so this is a
deterministic, transparent, tunable classifier instead.

Tiers:
- "high"   — convertible archetypes where his background IS the differentiated
             fit (GTM strategy/ops, competitive/market intelligence, applied AI,
             GTM specialist/systems, business/product strategy, chief of staff),
             plus 0->1 / AI-native / agentic roles that foreground building (there
             he's a differentiated, not conventional, applicant).
- "low"    — generic PM roles where a conventional PM track record is the primary
             screen and his GTM/builder edge isn't the hook.
- "medium" — everything else.

Ranking should order Strong/Perfect by (conversion desc, fit desc) so his
convertible archetypes surface above generic PM at equal fit.
"""
from __future__ import annotations

# Convertible archetypes — his background is the differentiated fit; recruiters call.
_HIGH_TITLE = (
    "strategy and operations", "business strategy", "business operations",
    "competitive intelligence", "market intelligence", "product intelligence",
    "applied ai", "gtm strateg", "go-to-market strateg", "gtm specialist",
    "go-to-market specialist", "worldwide specialist", "ww specialist",
    "partner specialist", "partner development", "gtm systems", "chief of staff",
    "product strategy", "genai strategist", "ai strategist", "revenue strategy",
    "sales strategy",
)
# Builder / 0->1 / AI-native signals: a "PM" role here foregrounds building, so
# he's a differentiated applicant -> high conversion despite the PM title.
_BUILDER = (
    "0-1", "0 to 1", "0->1", "agentic", "ai-native", "ai native",
    "incubation", "new products", "new bets",
)
# Generic PM title markers (conventional PM career gates the screen).
_PM = (
    "product manager", "product management", "group product manager",
    "product lead", "product owner", "product marketing", "pmt",
)

TIER_RANK = {"high": 2, "medium": 1, "low": 0}


def conversion_tier(title: str, raw_jd: str = "") -> str:
    """Deterministic callback-likelihood tier for Sam's background."""
    t = (title or "").lower().replace(" & ", " and ")
    if any(k in t for k in _HIGH_TITLE):
        return "high"
    ctx = f"{title} {raw_jd[:1000]}".lower().replace(" & ", " and ")
    if any(k in ctx for k in _BUILDER):
        return "high"
    if any(k in t for k in _PM):
        return "low"
    return "medium"
