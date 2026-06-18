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
  "education": "MBA, W.P. Carey / ASU; B.Tech Civil Engineering, BPUT"
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

### Full Company List (9)

**Scope:** The companies Sam is actively targeting (June 2026). Role-based discovery is gated by this whitelist; any ATS posting outside it is filtered out before scoring. (Prior 27-company list is in git history if a company needs to be re-added.)

1. **Anthropic** — Greenhouse (`anthropic`) — confirmed H1B
2. **OpenAI** — Ashby (`openai`) — confirmed H1B
3. **Amazon** — Sam's current employer; scoped to **Seattle + AWS/AGI orgs + Product Manager & GTM Specialist roles** via the amazon.jobs `search.json` API (`fetch_amazon_jobs()`); internal-transfer scoring — confirmed H1B
4. **Google DeepMind** — Google's frontier AI lab; structured Greenhouse board (`deepmind`) — confirmed H1B
5. **Google** (broader: Cloud AI, Labs, Workspace, YouTube) — web-search entry, Google-specific query in `_build_brave_query` scoped to careers + LinkedIn. Companion to Google DeepMind so discovery covers both — confirmed H1B
6. **Databricks** — Data + AI platform; Greenhouse (`databricks`), fully wired into ATS pipeline + daily cron — confirmed H1B (added 2026-06-15)
7. **NVIDIA** — AI infra/compute; **Workday CXS** board (`fetch_workday_jobs()`, `WORKDAY_BOARDS['nvidia']`), wired into ATS pipeline + daily cron — confirmed H1B (added 2026-06-15)
8. **Snowflake** — Data + AI platform (Cortex AI); moved off Greenhouse onto **Ashby** (`snowflake`); confirmed + wired into the ATS pipeline + daily cron 2026-06-15 — confirmed H1B
9. **CoreWeave** — AI/GPU cloud infra (public 2025); Greenhouse (`coreweave`), wired into ATS pipeline + daily cron — confirmed H1B (added 2026-06-15)

### Application strategy (set 2026-06-15)
- **Volume target: ≥15 applications/week.** Drives discovery breadth and the quick-apply digest; the bottleneck is qualifying-role supply, hence the company-list expansion.
- **Level-up rule (the hard filter for step-outs):** Sam will only leave Amazon for a non-Amazon company if the move is (a) to a company in the **at-level tier — OpenAI, Anthropic, Google, Google DeepMind** (join at-level is acceptable — these he wants on their own terms; Google added 2026-06-18), or (b) a genuine **level-up** over his current ~L6 AWS Sr Manager role. For **every other external company** (Databricks, NVIDIA, Snowflake, CoreWeave, future targets outside the at-level tier), only up-level roles (Head / Director / Principal / Lead / GM with real scope) should reach Strong/Perfect; lateral or lower roles cap at Good Match even with excellent domain fit. **Amazon internal** moves stay lateral-OK. This is enforced via the `global_notes` level rule in `config/scoring_adjustments.json` (plus per-company role-targeting notes), so it shapes scoring — and therefore notifications/digests — without code changes. Net effect: laterals at the still-capped step-out companies score below the 80 notify bar and stay out of the digest automatically, while at-level-tier laterals are scored on genuine fit.
- **Per-company application pacing caps** (Google 3/30-days + self-imposed 1/week; OpenAI 5/180-days) live in `samresume/CLAUDE.md`. The 15/week volume target is gross across all companies and must respect those per-company caps.

### Notifications policy
- **Per-role emails:** fire when a role meets its company notification bar. Default bar is Strong Match (overall_score ≥ 80); **Amazon's bar is 70** (Good Match+), because big-company JD-realism score caps push genuinely strong-fit Amazon roles into the 70–79 band. Bar is set in `notification_threshold()` / `COMPANY_NOTIFICATION_THRESHOLDS` in `notifications.py`. Email subject + header adapt to the role's actual match_tier.
- **Internal-transfer scoring (Amazon):** Sam currently works at Amazon (AWS), so Amazon roles are scored as internal transfers — `build_scoring_message()` injects an "Internal Transfer Context" block (`_is_internal_transfer()` in `scoring.py`). It lifts the big-company 84 cap (internal moves face a lower effective bar, no big-co onboarding friction), sets h1b_likelihood to 100, and tells the scorer to grade on genuine fit. Net effect: AI/GTM builder roles rise into Strong/Perfect while weak-fit roles settle to their true level — it differentiates, it doesn't blanket-inflate.
- **Daily digest:** sent when ≥1 qualifying match is found that day; body groups Perfect → Strong → Good sections, sorted by score descending within each. A role qualifies if it meets its company bar, so non-Amazon Good Matches (70–79) stay out of the digest while Amazon's appear. Skipped on days with zero qualifying matches.
- Resend free tier (100/day, 3,000/month) easily fits historical email volume at this threshold (~85 emails/month forecast).
- **Morning quick-apply digest:** a second, richer email that turns each NEW qualifying match (unreviewed, found in the last ~36h) into a copy-paste "apply in 5 minutes" packet: company, title, apply URL, tier/score, the resume base to attach, and the company-appropriate free-form answer(s) (Anthropic Why / OpenAI Additional Info / Google-DeepMind cover letter / Amazon internal fields). Built by `services/quick_apply.py` and **folded into `/discover/cron`** (no new Vercel cron) — runs after discovery+scoring each day. GENERATE-ONLY for cost: one Claude call per role with the persona prompt-cached, bounded by `QUICK_APPLY_MAX` (default 8); grounding is enforced by the system prompt + locked-in facts, with a deterministic post-scrub of em/en dashes and advisory flags from `agents/ai_tells.py`. Toggle with `CRON_ENABLE_QUICK_APPLY` (default true). Manual trigger/test: `POST /quick-apply/preview` (dry-run, no email) and `POST /quick-apply/cron` (sends), both Bearer `CRON_SECRET`. Deep voice/alignment review stays on the laptop-side scheduled task to keep cloud spend low. (Vercel discover cron moved to 15:00 UTC ≈ 8am PT so the email lands in the morning.)

### Daily cron scope
The Vercel cron (14:00 UTC daily) calls `/discover/cron` on the Railway backend, which scans the companies named in the `CRON_COMPANIES` env var. Current value (set on Railway and mirrored in local `.env`):

```
CRON_COMPANIES=Anthropic,OpenAI,Amazon,Google DeepMind,Google,Databricks,NVIDIA,Snowflake,CoreWeave
```

These 9 are the daily-scanned set. Databricks (Greenhouse), NVIDIA (Workday CXS client), Snowflake (Ashby, slug `snowflake` — moved off Greenhouse), and CoreWeave (Greenhouse, slug `coreweave`) were added 2026-06-15. Other companies in `companies.json` remain discoverable via the manual `/discover/{company}` endpoint and role-based discovery — just not scanned daily.

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
- **Application-update extractor (BUILT, 2026-06-15) — the inbox->outcome->Forge bridge.** `services/application_updates.py` + `POST /application-updates/ingest` (Bearer `CRON_SECRET`; `POST /application-updates/preview` for a no-write dry-run). A **daily Cowork scheduled task** ("application-response-tracker") uses the Gmail connector to scan for ATS replies (Greenhouse `greenhouse-mail.io`, Ashby, Lever, amazon.jobs, Gem `appreview.gem.com`, Workday, etc.) and POSTs the raw batch to the backend. The backend classifies each email (confirmation / rejection / interview_invite / online_assessment / offer) with Claude (Haiku, bounded by `MAX_EMAILS_PER_RUN`), matches it to a single role Sam engaged with (applied/interviewing/offer first, then any role at that company; title-similarity disambiguates), and updates `application_status` **through `services/outcomes.record_outcome()`** — the same single write path as PATCH `/roles/{id}`, so the calibration/return-path loop closes without manual entry. Status only progresses (never downgrades); a rejection is terminal at any stage. **Positive movement (interview invite, online assessment, or offer) auto-fires `generate_session_config()`** so a Forge interview-prep session is generated + pushed for that role. Idempotent + auditable via the `email_application_updates` table (`message_id` UNIQUE); ignores this app's own `onboarding@resend.dev` digests. Guarded by `L19`. The Cowork task needs `BACKEND_URL` + `CRON_SECRET` in `backend/.env` (CRON_SECRET already set; add `BACKEND_URL` = the Railway URL, already in Vercel env).

---

## Relationship to Other Projects
- **GenAI-Intel** (`cloud-intel.vercel.app`) — separate app, same stack. No shared DB.
- **Forge** (`forge-pi-livid.vercel.app`) — Phase 2 integration target. Sam owns both codebases.
- **AWS AI Executive Reporting Toolkit** — internal, not relevant to this app.
