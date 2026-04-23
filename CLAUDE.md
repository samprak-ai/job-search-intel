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
    "11+ years GTM + Sales Ops at AWS Startups",
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
- Match tiers: `Strong` / `Worth Applying` / `Stretch` / `Skip`
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

### Full Company List (23)

**Scope:** Big Tech + Mature AI-Forward Startups only. Focus on roles that enable rapid experimentation, learning, and influence. Role-based discovery is gated by this same whitelist — any ATS posting from a company outside this list is filtered out before scoring.

**Model Providers**
1. Anthropic — confirmed H1B
2. OpenAI — confirmed H1B
3. Cohere — confirmed H1B
4. Together AI — likely H1B
5. Perplexity — likely H1B
6. Mistral (US) — unknown H1B
7. xAI — unknown H1B

**Big Tech / Cloud AI**
8. Alphabet (Google/DeepMind) — confirmed H1B
9. Microsoft Azure AI — confirmed H1B
10. Databricks — confirmed H1B
11. Snowflake — confirmed H1B
12. Salesforce (Einstein AI) — confirmed H1B
13. LinkedIn (Microsoft) — confirmed H1B

**Mature AI-Forward Startups**
14. Scale AI — confirmed H1B
15. Notion — confirmed H1B
16. Glean — likely H1B
17. Writer — likely H1B
18. Moveworks — likely H1B
19. Ramp — confirmed H1B
20. Hugging Face — likely H1B
21. Weights & Biases — likely H1B
22. Replit — likely H1B
23. Runway — likely H1B

### Notifications policy
- **Per-role emails:** only for Perfect Match (overall_score ≥ 90)
- **Daily digest:** only sent when ≥1 Perfect Match is found that day; body shows Perfect Matches only (no Strong/Good/Possible/Unlikely tiers)

---

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
