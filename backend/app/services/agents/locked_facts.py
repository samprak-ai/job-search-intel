"""Single source of truth for Sam's locked-in facts.

The same facts are embedded inside `application_tailor.py`'s TAILORING_SYSTEM_PROMPT.
This module re-exports them so the critic agent and persona loader can reference
them without depending on the drafter. When updating facts, update both places
(application_tailor.py and this file) — a future refactor can consolidate.
"""

LOCKED_IN_FACTS_MARKDOWN = """## Startup Pulse
- WHAT IT ACTUALLY IS (lead with this, not the plumbing): a SYNTHESIS engine, not a collector. It takes a
  broad view across EXTERNAL market signal (funding, hiring, product launches, trust pages, job postings) and
  INTERNAL first-party data (revenue, growth, CRM engagement, pipeline) and DERIVES strategic metrics that
  exist in no source system: Primary Cloud Provider and Primary AI Provider. Aggregating what is already
  recorded is a dashboard. Deriving a number nobody reports is the hard part. Do NOT describe Startup Pulse as
  "gathering market intelligence" or "collecting signals" - that undersells it to the level of a BI report and
  loses the actual differentiator. The multi-agent pipeline is HOW; the derived metric is WHAT.
- Duration compression: EXACTLY "6 weeks to under a week" (not "2 weeks", not "multi-week to same-week")
- Hours recovered: EXACTLY "600 hours per cycle across three individuals" (not 480, not "hundreds of hours", not "65%")
- Time reduction: EXACTLY "70% reduction in report generation time" (not 65%, not "more than half")
- System scope: "2000+ strategic startups" - CONFIRMED ACCURATE TODAY (2026-07). Composition: ~1000 in the
  current quarterly cohort + ~1000 tracked historically for PCP changes = 2000+ universe. It is the TRACKED
  UNIVERSE, never a single report cohort.
- SCALE STORY (do not state a multiple - the comparison is not apples-to-apples and invites a challenge):
    * 2 years ago: manual report on 20-25 startups/month
    * Now: monthly cadence 50; quarterly cadence 1000 (began at 500); tracked universe 2000+
    * Projection: expecting to cross ~6K startups by end of 2026. FORWARD-LOOKING - label as a plan, never as
      current. Do NOT put 6K on a resume as a present-tense fact.
  The claims "50x" and "40x" are WRONG: 50 -> 2000 is 40x, and 50 is the CURRENT monthly, not the starting
  point. The real span is 20-25 -> 2000+ tracked. State the endpoints, not the multiple.
- The old locked fact "10x scale improvement" is STALE (it implied 50 -> 500). Do not cite 10x for scope.
- THE JUDGMENT DETAIL (use it - it is better than any multiple): the monthly cadence sits at 50 because that
  is what Andy Jassy can realistically review, NOT what the system can produce. The bottleneck moved from
  production capacity to human attention, and Sam stopped optimizing the wrong thing.
- LONGITUDINAL PCP-CHANGE DETECTION (was missing from all materials): the system tracks the previous ~1000
  startups and reports which ones have SWITCHED their primary cloud since the last cycle. A snapshot says
  where a startup runs; change detection says who was won and who was lost. That is the signal leadership
  acts on, and it is a stronger claim than the scale numbers.
- Citation: "cited by Andy Jassy in Amazon's Q4 2025 earnings call"
- Board review: "served as a primary metric in Amazon's end-of-year board review for AWS startup competitive positioning"
- Customer-facing label: "AWS's first AI-powered PCP and AI provider identification system"
- Architecture: multi-agent pipeline with data-gathering, consolidation, review, and formatting agents
- Reporting cadences (current): TWO. Monthly top-50 funded startups; quarterly top-1000.
  CORRECTED by Sam 2026-07-15: there are TWO cadences, not three. Do NOT write "three executive decision
  cadences", and do NOT list a top-500 / Bi-Weekly Business Review cohort as a Startup Pulse cadence.
  2000+ remains the TRACKED UNIVERSE (~1000 current quarterly cohort + ~1000 tracked historically for
  PCP change), not a report cohort - that composition is unaffected by the cadence count.

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
- ACCOUNTABILITY LOOP (Sam owns this - it is the "Operations" half of the job and was missing from all materials
  until 2026-07): Sam does not stop at the report. When PCP shows a startup is NOT on AWS, the account team commits
  a win-back plan in front of Andy Jassy's office, and SAM DRIVES THE FOLLOW-THROUGH - tracking those commitments
  and holding teams to them. Do NOT describe his work as "leadership uses the intelligence" (passive). He owns the
  mechanism that makes the org act on it: data finds the gap -> account team commits a plan -> Sam holds them to it.
  Related: Investor Pulse's notification agent drives the same accountable follow-through across Startup Investment
  Managers and Account teams, piped into Salesforce and Outlook. Most intelligence work dies at the report; this
  closes the loop, and that is an ownership claim, not an analysis claim.
- PAIP seeded dedicated competitive-intelligence reporting that synthesizes external public signals with internal CRM data for a holistic read on the evolving competitive landscape and AWS's response (this is the Competitor Pulse line of work).

## AWS Internal AI Platforms
- Approved names: "Amazon Kiro", "Amazon Quick", "PizzaBot"
- DO NOT use: "Amazon Q Spaces & Flows", "Amazon Q Flows", or "Amazon Q Spaces"
- Do NOT describe Quick generically as "the frontend" or Kiro as "the backend". Which tool runs what:
    * PCP app/product: Quick ONLY (own search engine for external signals; MCP connectors for Salesforce,
      1P revenue, 3P data). NO Kiro.
    * Startup Intelligence Hub (incl. the Startup 360 Knowledge Graph): Quick + Kiro
    * Automated report generator agent (Startup Pulse): Quick + PizzaBot. NO Kiro.
  NOTE on the resume: the entry titled "PCP Reference App - Startup 360 Knowledge Graph" covers BOTH, so its
  stack line legitimately carries Kiro (for the Startup 360 / Hub half). Do not read that as Kiro on PCP.

## Project Names (canonical)
- Investor Pulse (formerly Portfolio Intelligence Engine; do NOT use old name) - VC-intelligence briefing for Andy Jassy's office
- Competitor Pulse (formerly FlankWatch / Competitive Threat Monitor; do NOT use old names) - competitive-intelligence briefing for Andy Jassy's office. FULL SCOPE, all five, do not drop any (Sam caught hyperscalers missing 2026-07-15): hyperscalers, neoclouds, sovereign clouds, emerging developer tools, AI model providers (OpenAI, Anthropic). Hyperscalers are the primary competitive set - omitting them is the most conspicuous possible gap in a competitive-intelligence claim.
- Loss Signal Validator
- Startup Pulse
- PCP Reference App. WHAT IT IS, precisely (RE-clarified by Sam 2026-07-15 after I got this wrong):
  a LIGHTWEIGHT WEB APPLICATION, a ready-reference companion to Startup Pulse. Purpose-built around ONE
  metric: it returns Primary Cloud Provider for a single startup or a group of startups by reading across
  external and internal sources, and SHOWS THE EVIDENCE behind each inference.
  THE PROBLEM IT SOLVES (state it this way): before it, PCP was only knowable if a Startup Pulse report
  happened to cover that startup - and even then you waited a month or a quarter for the cycle. If a
  startup was not in the report, there was no way to get its PCP at all. The app removes the wait and the
  coverage gap.
  The evidence display is the point, not a nicety: it lets the person asking audit the answer instead of
  taking the verdict on faith. Same provenance principle as Cloud-Intel's citing knowledge-graph Q&A.
  DIVISION OF LABOUR - do not conflate these two:
    * Startup Pulse     = SCHEDULED cohort reporting (monthly 50, quarterly 1000). The heavyweight.
                          The PCP INFERENCE, its three-era evolution, the 1,000+ seller-conversation eval,
                          the 100%->under-30% manual-effort arc, and Jassy's-office-as-design-partner ALL belong
                          HERE, to the reporting system. NOT to the reference app.
    * PCP Reference App = AD-HOC, on-demand, one metric, with evidence. A lightweight read on the same
                          inference, so nobody has to wait for a report cycle. Do NOT attach the era story,
                          the eval, or the design-partner narrative to it.
  Failed prior approaches (third-party usage data / wallet-share proxies); Sam pioneered a qual+quant triangulation framework (~2.5 yrs ago) combining external signals (trust pages, job postings) + internal signals (Salesforce notes, revenue, growth, pipeline). Built on Quick ONLY (Kiro belongs to the Startup Intelligence Hub, not PCP). Internal: scope/behavior only, never internal numbers.
- Startup 360 Knowledge Graph (knowledge-graph semantic profiles enabling natural-language search over top startups, e.g. "which a16z-funded startups in the last 6 months are primarily on AWS?"; distinct from the 2021 Startup 360 seller mechanism)
- Proactive Intelligence Engine (Claude-side) - the frontier reference build of the pillar: watcher, classifier, account-manager writer; knowledge-graph memory; self-improving (propose-only) skill loop; frozen-fixture eval harness with bidirectional pairwise judging. Built on Claude Code, designed for Bedrock AgentCore. DUAL-BUILD intent: build the ideal state on the frontier (Claude), replicate within Amazon internal tooling, map what the jagged frontier enables to maximize internal value. Describe architecture/approach only (internal project); never internal data.
- Proactive Intelligence Pillar (Sam leads this, directing a cross-functional team of 7; one of six AI pillars across the AWS Startups segment. Mandate: move beyond prompts to agentic architecture - automate existing workflows and build new ones for Sales, Investment Managers, and Leadership)

## Vertical classification (corrected by Sam 2026-07-15)
- Sam did NOT originate vertical classification. A vertical taxonomy already existed at AWS Startups.
  NEVER write "originated the vertical-classification framework" - it is an overclaim.
- What he actually did, two parts:
    1. REDEFINED THE TAXONOMY so the classes map to cloud-spend-potential patterns, and so they reflect
       post-GenAI market realities the older categories predate.
    2. Made and socialized the STRATEGIC CASE that vertical, not funding size alone, should be the primary
       prioritization filter for high-potential startups. Funding size tells you who raised money, not who
       becomes a significant cloud consumer.
- Approved verb: "Redefined". Acceptable: "reworked", "rebuilt". Banned: "originated", "invented", "created
  from scratch", "pioneered" (reserve "pioneered" for PCP/PAIP, which he did pioneer).

## TENURE - THREE DISTINCT SPANS, DO NOT CONFLATE (corrected 2026-07-15)
Ground truth from profile.json work_history:
    Business Intelligence Engineer - PARTNER ORG    Aug 2019 - Dec 2020   <- AWS, but NOT Startups
    Go-to-Market Strategy Manager - Startups        Jan 2021 - Jun 2022
    Sr. GTM Strategy & Operations Manager, Startups Jun 2022 - Present
  * TOTAL EXPERIENCE : 12+ years   (incl. Infosys 2010-2013, Zamil 2015-2018)
  * AT AWS           : Aug 2019 -> now = ~7 years. Say "6.5+ years at AWS" (true, conservative).
  * AT AWS STARTUPS  : Jan 2021 -> now = ~5.5 years. NOT 6.5.

BANNED FORMS:
  - "6.5+ years at AWS Startups"  <- overstates Startups tenure by ~1 year. This was AWS-TOTAL tenure
      (computed ~early 2026) with "Startups" wrongly attached, and it propagated into ~50 files.
      It is disproved by the resume's own date column (BIE 2019-2020 = Partner Org).
  - "12+ years at AWS Startups"   <- conflates total with AWS tenure.
APPROVED FORMS:
  - "12+ years total experience, 6.5+ at AWS"  (used on the Google market-intel resume)
  - "~5.5 years at AWS Startups"  <- use when the sentence needs the STARTUPS-ecosystem claim
      specifically (e.g. "I know the startup ecosystem from N years at AWS Startups").
  - Never swap "6.5+ years at AWS" into a sentence that is making a Startups-ecosystem point; the two
    claims are different and need different numbers.

NOT retroactively fixed, by design: Legacy/, _superseded/, dated QuickApply_Packets_*.md snapshots, and
anthropic/perfect_matches/* per-role copies (samresume/CLAUDE.md Rule 4: per-role copies are not updated
retroactively unless Sam re-submits; several were already sent, and rewriting them would falsify the
record of what was actually submitted).

## Sam's Title / Experience
- NO formal Product Manager title.
- EXACTLY "12+ years total experience" AND "6.5+ years at AWS Startups".
- NEVER claim "12+ years at AWS Startups" — that conflates the two figures.
- "12+ years" must ALWAYS be qualified as total experience ("12+ years total experience" / "12+ years of experience"). NEVER attach "12+ years" to GTM/Strategy/Sales Ops or revenue/decision work as if that spanned 12 years — GTM/strategy tenure is the AWS years (~6.5), not 12.
- Do NOT cite LinkedIn as a data/discovery source in application materials; it is restricted for automated tools. (The linkedin.com profile URL in the contact line is fine.)
- Current role, TWO TITLES - do not mix them up:
    * HR / system-of-record title (what Amazon employment verification returns):
      "Sr. GTM Sales Operations Manager, Startups"
    * FUNCTIONAL title used on ALL EXTERNAL materials (resume, LinkedIn, cover letters, applications):
      "Sr. GTM Strategy & Operations Manager, Startups"
  Only the functional descriptor changes (Sales Operations -> Strategy & Operations). LEVEL AND SCOPE ARE
  UNCHANGED, and that is the whole point: it stays verifiable. Precedent: Sam's own prior AWS title was
  "Go-to-Market Strategy Manager, Startups", so the GTM Strategy title family demonstrably exists in this org.
  NEVER render it as "Sr. Manager, GTM Strategy & Operations" - at Amazon "Sr. Manager" is a LEVEL (and a level
  above Sam's), so that word order silently claims a promotion. "Sr. <function> Manager" is the correct shape.
  NEVER upgrade to Head of / Director / Principal. That is level inflation and it is what background checks catch.
  For AMAZON-INTERNAL applications, use the HR title ("Senior Sales Operations Manager") - internal systems
  already know it, and the functional title would look like an error there.
- Pair the title with the pillar, which is where the real scope lives:
  "Lead, Proactive Intelligence Pillar - one of six AI pillars across AWS Startups".
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

# Startup Intelligence Hub (Proactive Intel v2) - PROTOTYPING (never describe as shipped)
# - Where the Proactive Intelligence engine is heading: a real-time-updated repository of startup
#   profiles fusing three signal layers (first-party AWS data, web-based signals, derived signals)
#   into one living profile per startup. A knowledge graph runs over every profile for open-ended,
#   AI-driven natural-language queries. All derived signals are executed by an agentic framework
#   orchestrated through Hermes (the self-improving skill loop). Status: in design / prototyping.
#   Frame as "currently architecting / prototyping", never as a shipped/production system.

# AWS Penetration and Plan Review (strategy document) - Sam OWNS this for Andy Jassy's office
# - A strategy assessment on AWS's position with startups across revenue, primary cloud provider,
#   and pipeline, plus competitive insights, what's working, risks, and where the business needs help.
#   Use as evidence of strategic ownership at the CEO-office level. Internal: describe scope/ownership
#   only, never internal numbers or data.

# Trusted analytical partner for Andy Jassy's office (ongoing since June 2024)
# - The Top 100 AI Startups report (June 2024) was the ENTRY POINT, not the whole story. Sam has since
#   become the go-to analytical partner for Jassy's office on any startup question internal tagging
#   can't answer (strategic startups, embodied AI, AI-native SaaS disruptors, competitor performance
#   e.g. OCI), via cadenced and ad-hoc reports. Reaches the office through the Director of Startup Ops.
#   Describe as an ongoing trusted-partner relationship; scope only, never internal numbers.

# NAMING GUARD - the CEO-office strategy review
# - The internal document is named "AWS Penetration and Plan Review". Do NOT use that name in any
#   EXTERNAL artifact (resume, LinkedIn, portfolio, cover letters). Describe it generically as
#   "a recurring strategy review for Andy Jassy's office" on AWS's position with startups. Ownership
#   and scope carry the impact; the internal name adds nothing externally and should stay internal.

# Cloud-Intel status + framing (as of this update)
# - Cloud-Intel is a LIVE, reachable app (cloud-intel.vercel.app); the UI and collected data are browsable.
# - Its daily pipeline is PAUSED but restartable anytime. Do NOT claim it "runs ~2,500 analyses a day"
#   as a today-fact; frame as a pipeline that runs ~2,500 automated analyses PER CYCLE (capability).
# - Framing: Cloud-Intel is the personal PROOF-OF-CONCEPT Sam built to test the cloud/AI attribution
#   approach BEFORE building it for real inside AWS (the PCP/attribution work). Uses only public/external
#   signals. Label it "live proof-of-concept", not "production product".

# CORRECTION - Job Search Intel + Forge handoff is BUILT (not Phase 2)
# - services/forge.py generates a role-specific prep session (company interview philosophy, 5-7 likely
#   question themes with resume-leverage + directional angle, gap mitigation, opening pitch).
# - Forge's /interview-prep/import endpoint accepts that config (server-to-server, keyed).
# - Forge has a real AI mock interviewer: prompt library by company/role (~499 prompts), multi-turn
#   conversational interviewer (interview-conversation/assess), follow-ups, and delivery scoring.
# - The email application tracker auto-fires generate_session_config() on positive movement.
# So the full loop (match -> score -> role-specific prep -> push to Forge -> AI mock interview + scoring)
# is real and can be described as built. Earlier "Phase 2 / handoff TBD" note was stale.

# PCP PRODUCT JOURNEY - canonical narrative framing (added 2026-07-08)
# Full doc: samresume/_career_hub/05_pcp_product_journey.md (that file wins on conflict).
# Plot: a metric nobody could measure became a signal leadership acts on, and the hard part
# was never the model.
# SCOPE CORRECTION (Sam, 2026-07-15): this journey - the three eras, the design-partner framing,
# both arcs - is the journey of the PCP INFERENCE as it grew inside STARTUP PULSE, the scheduled
# reporting system. It is NOT the story of the PCP Reference App. The app is a later, lightweight
# ad-hoc read on that same inference (see its entry above). Attaching the eras or the design-partner
# narrative to the app is a factual error. I made it once; do not repeat it.
# - Andy Jassy's office is the DESIGN PARTNER, not "the first user". They set the accuracy bar
#   and reached for it repeatedly in live reviews. Adoption spread past the original requester.
#   Never claim classic "PMF" without that pull evidence; internal tools have captive users.
# - THREE ERAS (ordered by the product question each answered, not by stack):
#     1. "Is this even inferable?"  external-search-only prototype; no internal data to check
#        against, so it hallucinated confidently. The ceiling was the finding.
#     2. "Can anyone trust this?"   external + internal first-party data, model synthesizes the
#        PCP call. Fit happened here. The VALIDATION LAYER did it, not the model.
#     3. "Can this survive without me?"  rebuilt on Amazon Quick (own search engine for external;
#        MCP servers for Salesforce, 1P revenue, 3P data). Build-vs-adopt judgment.
# - TWO ARCS that carry the story: hallucinations -> decision-grade trust; 100% manual -> <30% manual.
#   CORRECTED by Sam 2026-07-15: the baseline was FULLY manual (100%), not ~75%. Never write '75%'.
#   These describe SAM'S OWN WORKFLOW, not AWS business results. That is why they are safe to state.
# - GROUND-TRUTH LOOP (lead with this): 1,000+ seller conversations over 2 yrs. Every seller
#   disagreement was a labeled example of where the inference was wrong; that built the eval.
# - Era-1 external-search VENDOR NAME: keep OUT of external materials. Say "an external-search-only
#   prototype". Vendor specificity is a detail about internal AWS architecture choices.
# - Era 3 is CURRENT. Never describe the bespoke Era-2 stack as what runs today.
# - Approved internal AI tool names: Quick, PizzaBot. Never "Amazon Q Spaces & Flows".

# GBrain / Hermes - ATTRIBUTION GUARD (added 2026-07-08, verified against proactive-intel source)
# These belong to PROACTIVE INTEL (the AWS Startups internal Claude-side prototype).
# They are NOT part of Cloud-Intel. Never attach them to Cloud-Intel, which is Sam's public
# attribution proof-of-concept built only on public/external signals.
#
# - GBrain is THIRD-PARTY, open source: github:garrytan/gbrain (Bun/TypeScript CLI, PGLite store).
#   Sam did NOT build GBrain. NEVER write "built GBrain" or imply authorship.
#   Sam BUILT: agents/gbrain_adapter.py (the Python bridge), the semantic net-new dedup, the typed
#   `about` edges to company pages, and the backend-agnostic memory seam (settings.MEMORY_BACKEND
#   switches between real GBrain and Sam's own agents/brain.py Supabase fallback).
#   Correct phrasing: "integrated GBrain, an open-source knowledge-graph store, via a Python adapter I wrote".
# - Hermes IS Sam's (agents/hermes.py). Propose-only: writes skills/_proposed/*.proposed.md and never
#   edits live skill files. Scores each brief + structured critique; calibrated against human AM
#   ratings collected via scripts/rate.py (am_feedback table).
# - STORAGE: GBrain uses PGLite. Do NOT say "Postgres/pgvector" for GBrain. pgvector appears only in
#   Sam's fallback agents/brain.py, where dense embeddings are seams-ready, NOT live.
# - RETRIEVAL: memory_context() is a hybrid VECTOR + KEYWORD query. Graph edges are WRITTEN, not used
#   as a retrieval path. Do NOT claim "graph-edge retrieval".
# - CORRECTION (verified live 2026-07-08): a knowledge-graph Q&A IS SHIPPED. cloud-intel.vercel.app/ask
#   ("Ask the Knowledge Graph") calls a Railway backend /api/ask and answers from the same graph
#   Proactive Intel writes into. Answers cite the graph pages used, e.g. [signals/tensormesh-79f929963429].
#   This is grounded generation WITH PROVENANCE and is safe to claim. What is NOT shipped: the
#   Startup Intelligence Hub's NL query over AWS first-party data (that remains v2, prototyping).
#   Keep those two claims distinct.
# - DEPLOYMENT SPLIT (verified): the graph store + /api/ask + the Next.js read UI are DEPLOYED.
#   The pipeline that populates them (scripts/run.py: watcher, classifier, writer) runs LOCALLY.
#   So: "a deployed knowledge-graph Q&A over a locally-run intelligence pipeline." Do not say the
#   pipeline is deployed, and do not say the Q&A is only a prototype.
# - Under-told but TRUE and strong (use these): zero net-new signals -> pipeline returns `no_change` and
#   skips the brief entirely (no writer spend, no filler); classifier confidence below MIN_CONFIDENCE
#   routes to `review_queue` instead of the writer; frozen-fixture eval replays at temperature 0 and
#   judges pairwise with BIDIRECTIONAL consistency (must win both orderings, else tie) to cancel position bias.
# - Proactive Intel is an INTERNAL AWS project: describe architecture/approach only, never internal data.
