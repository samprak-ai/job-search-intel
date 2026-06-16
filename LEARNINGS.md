# LEARNINGS — gap registry & self-improvement loop

This file is the durable memory half of the self-improvement loop. Every gap we
find (a regression, a missed role, a drift between docs and code) gets an entry
here. **A gap is not "done" until it is `guarded`** — i.e. it has either a
deterministic check in `backend/selfcheck.py` or an explicit manual step below.

How the loop works:
1. **Find a gap** (during dev, or auto-detected at runtime).
2. **Add a learning** here with its invariant.
3. **Guard it**: add a `selfcheck.py` check (preferred) or a manual procedure.
4. The Claude Code **Stop hook** runs `selfcheck.py` (static) so the guard can
   never silently lapse.

Run the guards anytime:
```
cd backend && python3 selfcheck.py        # static (fast, offline)
cd backend && python3 selfcheck.py --db   # + live-data invariants
```

Status legend: `guarded` (automated check) · `manual` (procedure, no automated
check yet) · `open` (found, not yet guarded — should be empty).

---

## Guarded invariants (enforced by selfcheck.py)

| ID | The gap we hit | Invariant | Guard |
|----|----------------|-----------|-------|
| **L1** | CLAUDE.md listed match tiers (`Strong/Worth Applying/Stretch/Skip`) that the code never used. A summary then propagated the stale names. | CLAUDE.md must contain the exact tier strings emitted by `scoring.py` and none of the stale ones. | `L1-tier-strings-consistent` |
| **L2** | The 80-vs-70 notification bar lived in two files; changing one missed the other. | The bar must come from `notification_threshold()` / `COMPANY_NOTIFICATION_THRESHOLDS` in `notifications.py`; `scoring.py` must call it, not hardcode. | `L2-notification-bar-single-source` |
| **L3** | `profile.json` Startup Pulse stats drifted from `locked_facts.py` (480h vs 600h, Bedrock vs Kiro), which made the critic emit false positives. | `profile.json` must contain the canonical locked facts (600 hours, 70%, Kiro) and none of the stale ones (480 hours, Amazon Q Spaces, Bedrock Agents). | `L3-profile-matches-locked-facts` |
| **L4** | Amazon job URLs were rejected (numeric IDs) / built without `www`, producing dead links. | `fetch_amazon_jobs` must build URLs as `https://www.amazon.jobs` + `job_path`. | `L4-amazon-url-construction` |
| **L5** | `CRON_COMPANIES` names must match `companies.json` exactly (e.g. "Alphabet" not "Google") or discovery silently no-ops. | Every documented `CRON_COMPANIES` name must exist in `companies.json`. | `L5-cron-companies-valid` |
| **L6** | The generic freshness check treated 403 as dead; amazon.jobs bot-throttles with 403, which would wrongly kill live roles. | Amazon freshness must route through `_check_amazon` (404/410 = dead; 403 = inconclusive). | `L6-amazon-freshness-403-safe` |
| **L7** | Re-scoring inserted new `role_scores` rows instead of replacing, creating duplicates. | No role may have more than one `role_scores` row. | `L7-no-duplicate-role-scores` (db) |
| **L8** | Easy to add a route module and forget to import/register it in `main.py` (silently dead endpoint). | Every `app/routes/*.py` module must be imported and `include_router()`-ed in `main.py`. | `L8-routers-registered` |
| **L9** | Migrations copied a `DISABLE ROW LEVEL SECURITY` line, leaving public tables world-readable/writable via the anon key (Supabase `rls_disabled_in_public`). | No migration may disable RLS; public tables keep RLS enabled (backend uses the `service_role` key, which bypasses RLS). | `L9-no-rls-disabled-in-migrations` |
| **L10** | A burst freshness sweep got 403-rate-limited by Google Careers and treated 403 as "dead" → false-marked live roles stale → they were deleted (lost the strong-fit Google roles). Same trap as L6 (Amazon) but in the generic path. | Freshness `DEAD_STATUSES` must not include 403 (or 429) — those are rate-limit/bot-block, inconclusive. Only 404/410 = gone. | `L10-freshness-403-not-dead` |

---

## Manual invariants (procedure, not yet auto-guarded)

These are harder to assert statically. Follow the procedure; promote to a
`selfcheck.py` guard when a good signal exists.

- **M1 — Multi-location filtering.** Amazon roles can list several locations
  with a non-Seattle *primary*. Location filters must check the full `locations`
  list, not just `normalized_location`. (See `_amazon_job_in_target_city`.)
- **M2 — Don't score/email stale roles.** `score_role(force=True)` bypasses the
  `is_live` guard. Before any bulk re-score, run a freshness pass first, or
  expired postings get scored and emailed as live (dead "View Original" links).
- **M3 — Keep search queries compact.** Brave returns HTTP 422 on long/complex
  queries. Amazon-style multi-group `site:` queries must stay short.
- **M4 — Normalize title abbreviations.** Amazon truncates "Manager"→"Mgr" and
  uses "PMT"/"PMM"; these break spelled-out keyword filters. Normalize in the
  fetcher.
- **M5 — One write path for outcomes.** Role `application_status` (selector) and
  `application_outcomes` (return path) must not drift into competing state. Both
  funnel through `services/outcomes.record_outcome()`; don't write
  `application_outcomes` directly from a new caller.
- **M8 — Only ingest/notify on freshness-verifiable sources.** Google Careers is
  a client-rendered SPA: a bot fetch returns 200 + a generic shell for both live
  and dead jobs, so its URLs can't be verified (we emailed a dead Strong Match).
  Prefer sources with a real liveness signal — ATS listing APIs, amazon.jobs
  (404), LinkedIn guest jobPosting (404). Google = LinkedIn-only (`linkedin_only`).
  Scoring now does verify-before-email: skip the notification if the posting is
  confirmed dead.
- **M7 — Verify clean dependency resolution before pushing requirements.txt.**
  An *incremental* local `pip install --upgrade <pkg>` can leave the venv working
  while `requirements.txt` is unresolvable on a fresh install (it bumps transitive
  deps past their pins silently) — which then fails Railway's clean build. Before
  pushing a dep change, run `pip install --dry-run --ignore-installed -r
  requirements.txt` and confirm exit 0. (Bit us: supabase 2.31 → realtime needs
  pydantic>=2.11.7 vs the pinned 2.10.4.)
- **M6 — Supabase key + RLS posture.** RLS is ENABLED on every table (no public
  policies). The backend MUST authenticate with a privileged key — the new
  `sb_secret_*` secret key (preferred) or the legacy `service_role` JWT — which
  bypasses RLS. The public `anon` key has zero access. Two gotchas: (1) the new
  `sb_secret_*` keys are NOT JWTs, so they need `supabase-py >= 2.15` (2.11
  rejected them as "Invalid API key"); (2) never expose the secret key
  client-side (`NEXT_PUBLIC_*`, frontend bundle, git). Set via
  `SUPABASE_SERVICE_KEY` (config falls back to `SUPABASE_KEY`).

- **L11 — Reviewer hard-blocks on groundedness; AI-tells are advisory.** The
  Anthropic-only `agents/critic` does not cover OpenAI/Google/DeepMind/Amazon
  drafts, and its tone check is only a 9-phrase banned list — it misses the
  broad "sounds AI-written" class (hype words, LLM-isms, dramatic openers,
  not-just-X-but-Y, tricolons) and never grades voice against Sam's real
  writing. The company-agnostic `services/reviewer.py` (POST `/review`) fills
  this: deterministic format + `agents/ai_tells.py` voice flags, plus LLM
  graders for groundedness (HARD BLOCK — any unsupported claim makes the verdict
  "block"), voice-similarity (vs sam-profile.md blockquotes), and company/role
  alignment (advisory). Invariant: groundedness stays a hard block, the AI-tell
  lexicon is non-empty, and the `/review` router is registered. Guarded by
  `L11-reviewer-groundedness-hardblock`.

- **L12 — Quick-apply digest is generate-only, grounded, bounded, and folded
  into the daily cron.** The morning quick-apply email (`services/quick_apply.py`)
  must not balloon cloud spend or emit ungrounded text. Invariants: one Claude
  call per role (no separate LLM reviewer in the cloud path — deep review stays
  on the laptop task), output bounded by `quick_apply_max`, the generation prompt
  carries the grounding rule + locked-in facts, it respects the
  `cron_enable_quick_apply` toggle, it is folded into `/discover/cron` (no new
  Vercel cron), and the `/quick-apply` router is registered. Guarded by
  `L12-quick-apply-generate-only-grounded`.

- **L13 — Accuracy guards: qualify "12+ years"; never cite LinkedIn as a source.**
  Two recurring overclaims to catch: (1) "12+ years" attached to GTM/Strategy/Sales
  Ops or revenue/decision work (Sam's GTM/strategy tenure is the AWS years, ~6.5;
  "12+ years" is TOTAL experience only), and (2) citing LinkedIn as a data/discovery
  source in application materials (it is restricted for automated tools; the
  linkedin.com profile URL in the contact line is fine). The reviewer's
  `deterministic_review` flags both (the 12+ years one as must-fix), and selfcheck
  keeps profile.json clean of them. Guarded by `L13-accuracy-claim-guards`.

- **L14 — Saved-roles are taste ground truth; broaden Amazon discovery + calibrate scoring.**
  Sam's Amazon-internal saved-roles list (June 2026) exposed two gaps: (1) discovery
  missed entire families he targets - Partner Specialist, Partner Development Manager,
  GenAI Strategist, Deal Intelligence/Automation PMT, Worldwide Specialist (Foundation
  Models / Accelerate Compute); (2) scoring under-rated L6 WWSO GenAI / Data & AI GTM
  Specialist roles (capped at Strong) that are his actual top picks. Fixed: added those
  families to `ats_clients.AMAZON_BASE_QUERIES` + `ROLE_KEYWORDS`, and added an Amazon
  `company_note` in `config/scoring_adjustments.json` that lifts L6 GTM/Partner-Specialist
  GenAI roles to strong role-type fit (without blanket-inflating unrelated roles). Re-run
  discovery + `POST /score/rescore` to apply. Guarded by `L14-amazon-saved-roles-calibration`.

- **L15 — Amazon writing-style lint for Amazon artifacts.** Amazon self-assessment
  writing avoids weasel words (roughly, approximately, various, significantly,
  many, etc.) and prefers "I" over "we/our" in self-assessment, with quantified
  claims. `reviewer.deterministic_review` runs an Amazon-only lint (gated on
  `company == "Amazon"`) flagging weasel words and we/our as advisory. Guarded by
  `L15-amazon-style-lint`.

- **L16 — Don't undersell the AI products by leading with the tool.** Lead with
  engineering/product substance and outcomes (multi-agent orchestration, the
  4-tier attribution engine at ~2,500 searches/day, eval harnesses, grounding,
  knowledge-graph memory); Claude Code / AI-assisted development is the method,
  mentioned once ("at the pace of an engineering team"), never the headline. The
  "shipped solo as a non-engineer" angle is a strength for AI-native companies
  (Anthropic/OpenAI/DeepMind/xAI) but is DROPPED for Amazon internal artifacts.
  Guidance in locked_facts; reviewer lints both (framing advisory; Amazon
  non-engineer must-fix). Guarded by `L16-ai-products-framing`.

- **L19 — Email application-update bridge must not fork outcome state.** The
  inbox->outcome->Forge bridge (`services/application_updates.py`, POST
  `/application-updates/ingest`) ingests ATS reply emails from a daily Cowork
  scheduled task (Gmail connector), classifies each (confirmation / rejection /
  interview_invite / online_assessment / offer), matches it to a single role Sam
  engaged with, and updates `application_status`. The write MUST go through
  `services.outcomes.record_outcome()` — identical to PATCH `/roles/{id}` — and
  must never INSERT `application_outcomes` directly (that would fork the return
  path; see M5). Status only progresses (never downgrades); a rejection is
  terminal at any stage. Positive movement (interview/OA/offer) fires
  `generate_session_config()` (Forge), idempotently. Ingestion is bounded by
  `MAX_EMAILS_PER_RUN`, idempotent via `email_application_updates.message_id`
  (UNIQUE), and ignores this app's own `onboarding@resend.dev` digests. Guarded
  by `L19-application-updates-bridge-single-write-path`.

- **L21 — Workday ATS client must stay wired for `workday` companies.** NVIDIA
  (added 2026-06-15) is on Workday, which the original pipeline didn't support —
  `fetch_jobs_from_ats` returned `[]` for it, so discovery silently found nothing.
  Fixed with a generic Workday CXS client: `fetch_workday_jobs(slug)` in
  `ats_clients.py`, routed via `elif platform == "workday"`, with per-company
  coordinates in `WORKDAY_BOARDS` (keyed by `ats_slug`; `nvidia` -> host
  `nvidia.wd5`, tenant `nvidia`, site `NVIDIAExternalCareerSite`). The CXS list
  endpoint is `POST /wday/cxs/{tenant}/{site}/jobs`; JD detail is a second GET per
  posting, so titles + US location are pre-filtered before paying for detail
  (bounded by `WORKDAY_DETAIL_CAP`). Invariant: every `companies.json` company with
  `ats_platform="workday"` must have a complete `WORKDAY_BOARDS` entry, and the
  dispatcher must route `workday`. Guarded by `L21-workday-client-wired`.
  NOTE: live fetch can't run in the offline sandbox (no network); the guard is
  static + the parser is unit-tested with a mocked CXS response. First real cron
  run on Railway is the live verification.

---

## Adding a new learning

1. Append a row (guarded) or bullet (manual) above with the gap + invariant.
2. If guardable: add a `@check("Lx-...")` function in `backend/selfcheck.py` and
   confirm it FAILS on the bad state and PASSES on the fix.
3. Re-run `python3 selfcheck.py`. Commit the learning + the guard together.
