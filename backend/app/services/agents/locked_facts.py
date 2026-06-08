"""Single source of truth for Sam's locked-in facts.

The same facts are embedded inside `application_tailor.py`'s TAILORING_SYSTEM_PROMPT.
This module re-exports them so the critic agent and persona loader can reference
them without depending on the drafter. When updating facts, update both places
(application_tailor.py and this file) — a future refactor can consolidate.
"""

LOCKED_IN_FACTS_MARKDOWN = """## Startup Pulse
- Duration compression: EXACTLY "6 weeks to under a week" (not "2 weeks", not "multi-week to same-week")
- Hours recovered: EXACTLY "600 hours per cycle across three individuals" (not 480, not "hundreds of hours", not "65%")
- Scale improvement: EXACTLY "10x scale improvement" (when cited)
- Time reduction: EXACTLY "70% reduction in report generation time" (not 65%, not "more than half")
- System scope: EXACTLY "2000+ strategic startups"
- Citation: "cited by Andy Jassy in Amazon's Q1 2026 earnings call"
- Board review: "served as a primary metric in Amazon's end-of-year board review for AWS startup competitive positioning"
- Customer-facing label: "AWS's first AI-powered PCP and AI provider identification system"

## Monthly Top Startups Report
- Cohort size: EXACTLY "175 high-potential startups across 7 cohorts"
- Audience: "CEO Matt Garman's office throughout FY24"
- DO NOT conflate this 175 number with Startup Pulse's 2000+ scope.

## Top 100 AI Startups Report
- Audience: "Andy Jassy's office"
- Coordination: "130+ account teams"
- Sam developed the ranking methodology.

## AWS Internal AI Platforms
- Use: "Amazon Kiro (Opus 4.7 backend)" and "Amazon Quick (frontend)" and "PizzaBot"
- DO NOT use: "Amazon Q Spaces & Flows", "Amazon Q Flows", or "Amazon Q Spaces"

## Project Names (canonical)
- Investor Pulse (formerly Portfolio Intelligence Engine; do NOT use old name)
- Competitor Pulse (formerly FlankWatch / Competitive Threat Monitor; do NOT use old names)
- Loss Signal Validator
- Startup Pulse
- PCP Reference App (leadership-facing, built on Kiro + Quick)
- Proactive Intel workstream (Sam currently leads this for AWS Startups)

## Sam's Title / Experience
- NO formal Product Manager title.
- EXACTLY "12+ years total experience" AND "6.5+ years at AWS Startups".
- NEVER claim "12+ years at AWS Startups" — that conflates the two figures.
- Current role: Sr. GTM Sales Operations Manager, Startups, at Amazon Web Services (2022-Present).

## Live AI Products (shipped independently on Claude Code)
- Cloud-Intel (cloud-intel.vercel.app)
- Forge (forge-pi-livid.vercel.app)
- Job Search Intel (job-search-intel.vercel.app)
- Count = 3 live independent AI products. Plus 4 AWS agentic systems. Total = 7 in production.

## Voice Rules (hard constraints)
- NO em dashes ("—"). Use colons, periods, parens, or " - " hyphens.
- No jargon-inflation phrases. Banned: "uniquely positioned", "mission-critical", "synergy",
  "leverage" as verb, "transformative", "passionate about", "cross-functional alignment",
  "drive outcomes", "scale initiatives", "strategic stakeholder alignment".
- Plain, direct prose. Concrete proof over abstract claims."""


# Quick lookup for critic: tone/banned-phrase rules in a checkable form
BANNED_PHRASES = [
    "uniquely positioned",
    "mission-critical",
    "synergy",
    "transformative",
    "passionate about",
    "cross-functional alignment",
    "drive outcomes",
    "scale initiatives",
    "strategic stakeholder alignment",
]

BANNED_CHARS = ["—", "–"]  # em dash, en dash
