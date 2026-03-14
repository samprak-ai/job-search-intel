# Job Search Intelligence

A personal job search platform that tracks target companies, discovers open roles, scores match quality against a candidate profile, generates tailored resumes, and surfaces interview preparation context.

Built by Sam Prakash.

## Stack

| Layer | Technology | Deployment |
|-------|-----------|------------|
| Backend | FastAPI (Python) | Railway |
| Frontend | Next.js 16 / React 19 / Tailwind 4 | Vercel |
| Database | Supabase (Postgres) | Supabase Cloud |
| AI | Claude API (Anthropic) | - |
| Search | Brave Search API | - |
| Email | Resend | - |

## Features

### Role Discovery
Searches across 25 target companies using Brave Search, targeting job boards (Greenhouse, Lever, Ashby, LinkedIn) and company career pages. Deduplicates by URL and scrapes full JD text. Runs on-demand per company or as a daily cron job.

### Match Scoring
Sends JD + candidate profile to Claude API for multi-dimensional scoring across domain fit, technical fit, seniority fit, role type fit, and H1B likelihood. Applies a realism filter (65%+ alignment on the right dimensions = strong match). Outputs a match tier: **Strong** / **Worth Applying** / **Stretch** / **Skip**.

### Resume Tailoring
Claude analyzes the JD against the full structured resume and produces a prioritization guide: reordered sections, bullet priorities (lead with / reword / deprioritize), keyword emphasis, and a tailored summary. Includes a grounding constraint that prevents fabricating expertise not evidenced in the actual resume.

### Resume Download (.docx)
Generates a tailored Word document from the tailoring output. A Node.js script (`docx` library) builds the resume programmatically with fuzzy matching for bullet priority application, section reordering, and skills filtering. Downloads directly from the frontend.

### Interview Intel
Searches Reddit, Levels.fyi, and company hiring pages for interview process details. Claude summarizes into interview structure, question themes, emphasis areas, and culture signals.

### Daily Digest
A Vercel Cron (14:00 UTC) triggers discovery for configured companies, with results emailed via Resend.

### Forge Integration
Generates session configs for the [Forge](https://github.com/samprak-ai/forge) communication practice app, pre-loading company-specific question themes and competency areas from match gaps.

## Project Structure

```
backend/
  app/
    routes/          # FastAPI route handlers
      discover.py    # Role discovery endpoints
      score.py       # Match scoring endpoints
      intel.py       # Interview intel endpoints
      resume_tailor.py  # Tailoring + .docx download
      roles.py       # Role CRUD + listing
      forge.py       # Forge session handoff
      usage.py       # API usage tracking
    services/        # Business logic
      discovery.py   # Brave Search + JD scraping
      scoring.py     # Claude match scoring
      intel.py       # Interview intel gathering
      resume_tailor.py  # Claude tailoring prompts
      brave_search.py   # Brave API client
      jd_scraper.py     # JD text extraction
      ats_clients.py    # ATS-specific parsers
      notifications.py  # Email via Resend
    config.py        # Settings, Supabase client, profile loader
  config/
    profile.json     # Candidate resume data (structured)
    companies.json   # 25 target companies with metadata
  scripts/
    generate_resume.js  # Node.js .docx generator
  nixpacks.toml      # Railway build: Python + Node.js
  railway.toml       # Railway deploy config

frontend/
  src/app/
    page.tsx         # Landing page
    dashboard/       # Role discovery dashboard (sortable, filterable)
    role/[id]/       # Role detail: JD, scoring, tailoring, download
    companies/       # Company list view
    api/cron/        # Vercel Cron endpoint for daily discovery
  vercel.json        # Cron schedule config

supabase/
  schema.sql         # Core tables: roles, role_scores, interview_intel, sessions
  migration_*.sql    # Incremental migrations
```

## Database Schema

| Table | Purpose |
|-------|---------|
| `roles` | Discovered job postings (title, company, URL, JD text, application status) |
| `role_scores` | Match scoring results (tier, dimension scores, rationale, gaps) |
| `resume_tailors` | Claude-generated tailoring advice per role |
| `interview_intel` | Interview framework summaries per company/role type |
| `sessions` | Forge session configs linked to roles |

## Target Companies (25)

**Model Providers:** Anthropic, OpenAI, Cohere, Together AI, Perplexity, Mistral, xAI

**Big Tech / Cloud AI:** Alphabet, Microsoft (Azure AI), Databricks, Snowflake, Salesforce (Einstein AI)

**GTM & Revenue Intelligence:** Clay, 6sense, Common Room, Pocus, Demandbase, Amplemarket

**Data & Startup Intelligence:** Crunchbase, PitchBook, Similarweb, Bombora

**AI-native GTM / Emerging:** Qualified, Keyplay, LinkedIn

## Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- Supabase project
- API keys: Anthropic, Brave Search, Resend

### Backend
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd scripts && npm install && cd ..
cp .env.example .env  # fill in your keys
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE=http://localhost:8000" > .env.local
npm run dev
```

### Database
Run `supabase/schema.sql` in the Supabase SQL Editor, then apply migrations in order.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon key |
| `ANTHROPIC_API_KEY` | Claude API key |
| `BRAVE_API_KEY` | Brave Search API key |
| `RESEND_API_KEY` | Resend email API key |
| `NOTIFICATION_EMAIL` | Daily digest recipient |
| `CRON_SECRET` | Secret for cron endpoint auth |
| `CRON_COMPANIES` | Comma-separated company list for daily discovery |
| `FORGE_API_URL` | Forge app URL for session handoff |
| `FORGE_IMPORT_KEY` | Forge API auth key |
| `FRONTEND_URL` | Frontend URL for CORS |

## Deployment

**Backend (Railway):** Auto-deploys from `main` branch. Nixpacks builds with Python + Node.js. Root directory set to `backend/`.

**Frontend (Vercel):** Auto-deploys from `main` branch. Root directory set to `frontend/`. Cron job runs daily at 14:00 UTC.

## Related Projects

- **[Forge](https://github.com/samprak-ai/forge)** — Communication practice app with AI-scored writing and speaking reps
- **[GenAI-Intel](https://cloud-intel.vercel.app)** — Separate intelligence platform, same stack
