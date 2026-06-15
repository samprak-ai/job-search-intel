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
- Architecture: multi-agent pipeline with data-gathering, consolidation, review, and formatting agents
- Reporting cadences (current): monthly top-50 funded startups; quarterly top-1000; top-500 for the Bi-Weekly Business Review (BWBR), reviewed by Andy Jassy and his direct reports. 2000+ is the tracked universe, not a report cohort.

## Monthly Top Startups Report (historical, FY24)
- FY24 cohort size: EXACTLY "175 high-potential startups across 7 cohorts" for "CEO Matt Garman's office throughout FY24".
- CURRENT monthly cadence is the top-50 funded startups (see Reporting cadences above). Do not present the 175 as current.
- DO NOT conflate the 175 number with Startup Pulse's 2000+ tracked universe.

## Top 100 AI Startups Report
- Audience: "Andy Jassy's office"
- Coordination: "130+ account teams"
- Sam developed the ranking methodology.

## Primary Cloud Provider (PCP) and Primary AI Provider (PAIP)
- Sam's AI scale-up over the past year moved PCP from an obscure data point to the most-tracked metric in the AWS Startup organization: a front-and-center business metric mandated from Andy Jassy's office and adopted across AWS leadership.
- Sam PIONEERED Primary AI Provider (PAIP) as a companion metric. Rationale: PCP data showed little evidence of startups choosing neoclouds, so the lens was expanded to capture who startups use for AI workloads, which surfaced neoclouds and GPU providers. PAIP is forward-looking: as cloud spend shifts to GPUs, it flags rising GPU workloads on a neocloud before that provider becomes the startup's primary cloud.
- PAIP seeded dedicated competitive-intelligence reporting that synthesizes external public signals with internal CRM data for a holistic read on the evolving competitive landscape and AWS's response (this is the Competitor Pulse line of work).

## AWS Internal AI Platforms
- Use: "Amazon Kiro (Opus 4.7 backend)" and "Amazon Quick (frontend)" and "PizzaBot"
- DO NOT use: "Amazon Q Spaces & Flows", "Amazon Q Flows", or "Amazon Q Spaces"

## Project Names (canonical)
- Investor Pulse (formerly Portfolio Intelligence Engine; do NOT use old name) - VC-intelligence briefing for Andy Jassy's office
- Competitor Pulse (formerly FlankWatch / Competitive Threat Monitor; do NOT use old names) - competitive-intelligence briefing for Andy Jassy's office; covers neoclouds, sovereign clouds, emerging developer tools
- Loss Signal Validator
- Startup Pulse
- PCP Reference App (leadership-facing web app for on-demand startup PCP lookup; synthesizes external + AWS-internal sources to infer PCP and feed startup strategy; built on Kiro + Quick; rollout to the wider Sales org underway)
- Startup 360 Knowledge Graph (knowledge-graph semantic profiles enabling natural-language search over top startups, e.g. "which a16z-funded startups in the last 6 months are primarily on AWS?"; distinct from the 2021 Startup 360 seller mechanism)
- Proactive Intelligence Engine (Claude-side) - the frontier reference build of the pillar: watcher, classifier, account-manager writer; knowledge-graph memory; self-improving (propose-only) skill loop; frozen-fixture eval harness with bidirectional pairwise judging. Built on Claude Code, designed for Bedrock AgentCore. DUAL-BUILD intent: build the ideal state on the frontier (Claude), replicate within Amazon internal tooling, map what the jagged frontier enables to maximize internal value. Describe architecture/approach only (internal project); never internal data.
- Proactive Intelligence Pillar (Sam leads this, directing a cross-functional team of 7; one of six AI pillars across the AWS Startups segment. Mandate: move beyond prompts to agentic architecture - automate existing workflows and build new ones for Sales, Investment Managers, and Leadership)

## Sam's Title / Experience
- NO formal Product Manager title.
- EXACTLY "12+ years total experience" AND "6.5+ years at AWS Startups".
- NEVER claim "12+ years at AWS Startups" — that conflates the two figures.
- "12+ years" must ALWAYS be qualified as total experience ("12+ years total experience" / "12+ years of experience"). NEVER attach "12+ years" to GTM/Strategy/Sales Ops or revenue/decision work as if that spanned 12 years — GTM/strategy tenure is the AWS years (~6.5), not 12.
- Do NOT cite LinkedIn as a data/discovery source in application materials; it is restricted for automated tools. (The linkedin.com profile URL in the contact line is fine.)
- Current role: Sr. GTM Sales Operations Manager, Startups, at Amazon Web Services (2022-Present).
- Performance rating: "Exceeds High Bar" for two consecutive years (Amazon's top rating tier). Use this phrasing exactly; do not inflate (e.g., not "top 1%").

## Live AI Products (shipped independently on Claude Code)
- Cloud-Intel (cloud-intel.vercel.app)
- Forge (forge-pi-livid.vercel.app)
- Job Search Intel (job-search-intel.vercel.app)
- Count = 3 live independent AI products. Plus 4 AWS agentic systems. Total = 7 in production.

## Forge scoring (verified from code)
- Writing scored on 4 dimensions: clarity, structure, concision, persuasion.
- Speaking (Whisper-transcribed) scored on 4 dimensions: vocabulary, confidence, articulation, alignment.
- Forge also has interview-prep / mock-interview-round modes that import role/company prompt packs from Job Search Intel.
- Do NOT claim 5 dimensions for Forge speaking; it is 4. (Job Search Intel scores ROLES on 5 dimensions - that 5 is correct and separate.)

## Framing the AI products (how to write about them)
- Lead with the engineering and product SUBSTANCE and outcomes: multi-agent orchestration, the 4-tier attribution engine (~2,500 searches/day), eval harnesses (frozen-fixture, bidirectional pairwise judging), knowledge-graph memory, grounding/no-fabrication constraints, confidence scoring, self-improving loops.
- Claude Code / AI-assisted development is the METHOD, mentioned once as a force-multiplier ("built at the pace of an engineering team"), never the headline. Do NOT open with "built using/with Claude Code."
- The "shipped production AI systems solo as a non-engineer / self-taught" angle is a STRENGTH for AI-native companies (Anthropic, OpenAI, Google DeepMind, xAI) - use it there. DROP it entirely for Amazon (internal) artifacts.

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
