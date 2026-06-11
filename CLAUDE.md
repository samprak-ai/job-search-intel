# Job Search Intelligence App — Project Context for Claude Code

## What This Is
A personal job search intelligence platform built by Sam Prakash. Tracks target companies, discovers open roles, scores match quality against Sam's profile, and surfaces interview preparation context. Architecturally consistent with GenAI-Intel — same stack, same philosophy.

---

## Stack
- **Backend:** FastAPI (Python), deployed on Railway
- **Frontend:** Next.js, deployed on Vercel
- **Database:** Supabase (new project, separate from GenAI-Intel)
- **AI:** Claude API (Anthropic)
- **Search:** Brave Search API
- **Auth:** Supabase Auth (single user — Sam)

---

## Architecture Overview

### Static Config Files (no DB)
- `profile.json` — Sam's resume, positioning, differentiators, target role types
- `companies.json` — 25 target companies with metadata (tier, H1B status, priority, careers URL)

### Supabase Tables (operational data)
- `roles` — discovered job postings (title, company, url, date_found, raw_jd)
- `role_scores` — match scoring results (match_tier, rationale, gaps, scored_at)
- `interview_intel` — interview framework summaries per company/role type
- `sessions` — (Phase 2) Forge session configs linked to roles

### Backend Modules (FastAPI)
1. **Role Discovery** (`/discover`) — Brave Search queries per target company, parses job listings, deduplicates, stores to `roles`
2. **Match Scoring** (`/score/{role_id}`) — Sends JD + profile context to Claude API, returns match tier + rationale + gaps
3. **Interview Intel** (`/intel/{company}`) — Brave Search targeting Reddit, Levels.fyi, company hire pages; Claude summarizes into question frameworks
4. **Forge Handoff** (`/forge/session/{role_id}`) — Phase 2, generates session config for Forge from role + score + intel

### Frontend (Next.js)
- `/dashboard` — table of discovered roles with match tier badges, sortable/filterable
- `/role/[id]` — role detail: full JD, match rationale, gaps, interview intel
- `/companies` — company list view, editable priority/notes (writes back to companies.json or a UI layer over it)

---

## Module Specs

### Module 1 — Role Discovery
- Reads `companies.json` for target list
- Constructs Brave Search queries: `"{company_name}" "{role_keywords}" job opening site:greenhouse.io OR site:lever.co OR site:linkedin.com OR site:careers.{company_domain}`
- Role keywords derived from `profile.json` target role types
- Deduplicates by URL
- Stores raw JD text, title, company, source URL, date found to `roles` table
- Can be triggered manually or on a schedule (daily cron via Railway)

### Module 2 — Profile Context (Static)
`profile.json` structure:
```json
{
  "name": "Sam Prakash",
  "location": "Renton, WA",
  "target_role_types": [
    "AI Solutions Engineer",
    "AI Partnerships",
    "Head of AI Product",
    "GTM Strategy AI",
    "Sales Intelligence AI"
  ],
  "differentiators": [
    "Built production AI systems end-to-end (GenAI-Intel, Forge, AWS internal agents)",
    "12+ years GTM + Sales Ops at AWS Startups",
    "Rare fluency across business strategy, AI infrastructure, and hands-on product building",
    "Live deployed products as proof, not just claims"
  ],
  "experience_summary": "...",
  "skills": ["FastAPI", "Next.js", "Supabase", "Claude API", "Python", "SQL", "Salesforce", "AWS"],
  "education": "MBA, W.P. Carey / ASU; B.Tech EE, BPUT"
}
```

### Module 3 — Match Scoring
- Input: JD text + full `profile.json`
- Claude API prompt instructs:
  - Score alignment across 5 dimensions: domain fit, technical fit, seniority fit, role type fit, H1B likelihood
  - Apply JD realism filter (posted requirements are often inflated — 65%+ alignment on the right dimensions = strong match)
  - Output structured JSON: `{ match_tier, overall_score, dimension_scores, rationale, gaps, cover_letter_angles }`
- Match tiers (score bands): `Perfect Match` (90–100) / `Strong Match` (80–89) / `Good Match` (70–79) / `Possible Match` (60–69) / `Unlikely Match` (<60). These are the exact strings emitted by `scoring.py` and stored in `role_scores.match_tier` — keep this list in sync with the prompt's tier definitions.
- Stored to `role_scores` table

### Module 4 — Interview Intel (Lite)
- Input: company name + role type
- Brave Search queries:
  - `"{company}" "{role_type}" interview questions reddit`
  - `"{company}" interview process site:levels.fyi`
  - `"{company}" how we hire`
  - `"{company}" "{role_type}" interview experience`
- Claude API summarizes results into:
  - Interview structure (rounds, format)
  - Likely question themes and frameworks
  - Emphasis areas (what they care about most)
  - Any culture/values signals
- Stored to `interview_intel` table, keyed by `(company, role_type)`

### Module 5 — Forge Integration (Phase 2)
- Generates a session config object from: role details + match gaps + interview intel
- Forge accepts this config to pre-load a practice session with:
  - Company-specific question themes
  - Competency areas to emphasize
  - Sam's identified gaps to work on
- Handoff mechanism: shared Supabase record OR direct API call to Forge backend (TBD based on Forge architecture)

---

## companies.json Structure
```json
{
  "target_companies": [
    {
      "name": "Anthropic",
      "tier": "model_provider",
      "h1b_status": "confirmed",
      "priority": 1,
      "careers_url": "https://www.anthropic.com/careers",
      "notes": ""
    }
  ]
}
```

### Full Company List (27)

**Scope:** Frontier model labs + Big Tech AI divisions + mature AI-forward startups (horizontal and vertical) + frontier research orgs. Focus on **0→1 builder-operator roles** at companies where AI is the product (not a feature) and everyone builds by default. Role-based discovery is gated by this whitelist — any ATS posting from a company outside this list is filtered out before scoring.

**Model Providers (frontier labs)**
1. Anthropic — confirmed H1B
2. OpenAI — confirmed H1B
3. Cohere — confirmed H1B
4. Together AI — likely H1B
5. Perplexity — likely H1B
6. Mistral (US) — unknown H1B (verify)
7. xAI — unknown H1B (verify)

**Big Tech / Cloud AI**
8. Google DeepMind (Google's frontier AI lab; structured Greenhouse board, slug `deepmind`. Replaced the old web-search "Alphabet" entry — postings are branded Google/DeepMind, not "Alphabet") — confirmed H1B
8b. Google (broader Google: Cloud AI, Labs, Workspace, YouTube; web-search entry, Google-specific query in `_build_brave_query` scoped to careers + LinkedIn. Companion to Google DeepMind so discovery covers both) — confirmed H1B
9. Databricks — confirmed H1B
10. Snowflake — confirmed H1B
11. Salesforce (verify team has build-first culture) — confirmed H1B
12. LinkedIn — confirmed H1B
13. Amazon (Sam's current employer; scoped to **Seattle + AWS/AGI orgs + Product Manager & GTM Specialist roles** via the amazon.jobs `search.json` API — `fetch_amazon_jobs()` in ats_clients.py. Seattle match includes multi-location roles where Seattle is one of several posted locations; 20/query-family per run) — confirmed H1B

**Mature Horizontal AI Startups**
14. Notion — confirmed H1B
15. Glean — likely H1B
16. Ramp — confirmed H1B
17. Hugging Face — likely H1B
18. Weights & Biases — likely H1B
19. Replit — likely H1B
20. Runway — likely H1B

**AI-Native Vertical SaaS**
21. Harvey (legal AI) — likely H1B
22. Sierra (customer experience AI) — likely H1B
23. Decagon (customer service AI) — likely H1B
24. Cresta (contact center AI) — likely H1B
25. Abridge (healthcare AI) — likely H1B

**Frontier Research Orgs**
26. Ai2 (Allen Institute for AI) — likely H1B (comp may be tight for non-research roles)
27. Imbue (reasoning + agents research) — likely H1B

### Notifications policy
- **Per-role emails:** fire when a role meets its company notification bar. Default bar is Strong Match (overall_score ≥ 80); **Amazon's bar is 70** (Good Match+), because big-company JD-realism score caps push genuinely strong-fit Amazon roles into the 70–79 band. Bar is set in `notification_threshold()` / `COMPANY_NOTIFICATION_THRESHOLDS` in `notifications.py`. Email subject + header adapt to the role's actual match_tier.
- **Internal-transfer scoring (Amazon):** Sam currently works at Amazon (AWS), so Amazon roles are scored as internal transfers — `build_scoring_message()` injects an "Internal Transfer Context" block (`_is_internal_transfer()` in `scoring.py`). It lifts the big-company 84 cap (internal moves face a lower effective bar, no big-co onboarding friction), sets h1b_likelihood to 100, and tells the scorer to grade on genuine fit. Net effect: AI/GTM builder roles rise into Strong/Perfect while weak-fit roles settle to their true level — it differentiates, it doesn't blanket-inflate.
- **Daily digest:** sent when ≥1 qualifying match is found that day; body groups Perfect → Strong → Good sections, sorted by score descending within each. A role qualifies if it meets its company bar, so non-Amazon Good Matches (70–79) stay out of the digest while Amazon's appear. Skipped on days with zero qualifying matches.
- Resend free tier (100/day, 3,000/month) easily fits historical email volume at this threshold (~85 emails/month forecast).

### Daily cron scope
The Vercel cron (14:00 UTC daily) calls `/discover/cron` on the Railway backend, which scans the companies named in the `CRON_COMPANIES` env var. Current value (set on Railway and mirrored in local `.env`):

```
CRON_COMPANIES=Anthropic,OpenAI,Amazon,Google DeepMind,Google
```

These 10 are a deliberately bounded subset of the 26-company whitelist to keep cron runtime under ~15 minutes. The other 16 companies in `companies.json` are still discoverable via the manual `/discover/{company}` endpoint and via role-based discovery — they're just not scanned daily.

If you change this list:
1. Update Railway env var via dashboard
2. Update local `.env` to match (so local dev mirrors prod)
3. Update this section of CLAUDE.md
4. Names must match the `name` field in `backend/config/companies.json` exactly

### Target role types (sharpened after structured interview — see `/Users/Sam/Desktop/samresume/_context/sam-profile.md`)
- GTM Systems & Agents Lead
- AI Product Strategy & Growth Lead
- Applied AI Lead (customer-outcome, non-engineering)
- Chief of Staff to CPO / Head of AI / CRO (with build scope)
- Senior / Lead AI Product Manager
- Head of AI Product (hands-on, mid-stage companies)

---

## Self-improvement loop (gap → guard → tune)
The system is built to get monotonically better as gaps are found. A gap is never "just fixed" — it must leave a durable artifact. Three planes:

1. **Guard (engineering regressions)** — `LEARNINGS.md` registry + `backend/selfcheck.py` deterministic checks (one per learning). The Claude Code **Stop hook** (`.claude/settings.json`) runs the static checks on every task end and blocks completion (exit 2) if any invariant regressed. Run manually: `cd backend && python3 selfcheck.py [--db]`. **A gap isn't done until it has a selfcheck entry or a manual procedure in LEARNINGS.md.**
2. **Auto-capture (runtime/product gaps)** — `detected_gaps` table. The system logs its own gaps: `prediction_overconfident` / `prediction_underconfident` / `taste_mismatch` (from `application_outcomes` vs the snapshotted prediction, via `services/gaps.py`), `stale_high_score` (freshness), plus `manual` gaps via `POST /detected-gaps`. The **return path** is `application_outcomes` (predicted tier/score snapshotted at log time; `GET /application-outcomes/calibration`).
3. **Reflection (tuning)** — `POST /reflect` (`services/reflection.py`) reads outcomes + open gaps, and Claude proposes calibration findings + concrete changes (scoring notes, new guards, discovery keywords, intel refresh). **Nothing auto-applies** — it emails/returns a report for Sam to approve. Runs weekly via Vercel cron (`/api/cron/reflect` → `/reflect/cron`, Sundays 16:00 UTC).

**Closing the loop (outcomes → scoring):** Outcomes are recorded through one write path — `services/outcomes.record_outcome()` — fed by the role status selector (PATCH `/roles/{id}`) and the `/application-outcomes` API. It snapshots the prediction and auto-captures a calibration gap. Approved reflection notes persist in the `scoring_adjustments` table (durable across Railway redeploys; `config/scoring_adjustments.json` is an optional manual override merged in by `load_scoring_adjustments()`). `build_scoring_message()` appends active notes as a "Calibration adjustments" block so future scores actually shift. Full closed loop: outcome → gap → reflection proposal → approved note → changed scoring.

**Operator UI:** the `/insights` page is the loop control panel — predicted-vs-actual calibration table (`/application-outcomes/calibration`), a "Run reflection" button that renders proposals with one-click **Approve** (POST `/scoring-adjustments`), the active adjustments (deactivatable), and open detected gaps. Approving from the UI is the no-JSON-editing path.

Adding a learning: append to `LEARNINGS.md`, add a `@check` to `selfcheck.py` (confirm it fails-on-bad / passes-on-fix), commit both together.

## Key Design Principles
- **Single user app** — no multi-tenancy needed, keep auth simple
- **Manual triggers first** — no complex scheduling until core loop works
- **Same patterns as GenAI-Intel** — Brave Search → structured enrichment → LLM inference → dashboard
- **Profile is static config** — not operational data, lives in repo, versioned with code
- **Companies list is flexible** — JSON array, one-line add/remove, extendable fields
- **Claude API for all inference** — match scoring, intel summarization, gap analysis

---

## Phase 1 MVP Definition
Working end-to-end loop:
1. Trigger role discovery for all 25 companies
2. View discovered roles in dashboard with basic metadata
3. Trigger match scoring for any role
4. View match tier, rationale, and gaps on role detail page
5. Trigger interview intel fetch for a company
6. View interview framework summary on role detail page

Phase 1 is complete when the above loop works for at least one company end-to-end.

---

## Phase 2
- Forge session config generation and handoff
- Scheduled daily role discovery (Railway cron)
- Email/notification when Strong match found
- Company notes and application status tracking in dashboard

---

## Relationship to Other Projects
- **GenAI-Intel** (`cloud-intel.vercel.app`) — separate app, same stack. No shared DB.
- **Forge** (`forge-pi-livid.vercel.app`) — Phase 2 integration target. Sam owns both codebases.
- **AWS AI Executive Reporting Toolkit** — internal, not relevant to this app.
