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

---

## Adding a new learning

1. Append a row (guarded) or bullet (manual) above with the gap + invariant.
2. If guardable: add a `@check("Lx-...")` function in `backend/selfcheck.py` and
   confirm it FAILS on the bad state and PASSES on the fix.
3. Re-run `python3 selfcheck.py`. Commit the learning + the guard together.
