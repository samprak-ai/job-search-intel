# Dev-Task Benchmark — DeepSeek quality gate (opencode)

Purpose: objectively measure whether DeepSeek can do real work on this repo before
any runtime-AI swap. Each task is a real bug that was already fixed in git history;
the "candidate" gets only the bug symptom and must fix it. Grading is deterministic
via `backend/selfcheck.py` — every task maps to an L-check that fails if the fix is
wrong or missing, and most embed behavioral unit tests that import the code and
assert on its behavior.

## How to run a task

1. In a scratch branch, revert the fix commit listed for the task:
   `git revert <commit> --no-commit` (or `git checkout <commit>^ -- <file>` for a
   single file). Confirm `python3 selfcheck.py` now FAILS that task's checks.
2. Hand the model ONLY the "Symptom" text (no diff, no fix hint).
3. After its edit, grade:
   `cd backend && python3 selfcheck.py` — the task's checks must PASS.
   Optionally `python3 selfcheck.py --db` for DB-touching tasks.
4. Record: pass/fail per check, diff size vs the historical fix, and the model's
   own rationale. Compare against the historical commit's `Co-Authored-By`.

Grading is pass/fail, not vibes. A task is done only when its L-check(s) pass.

---

## Task list

### B1 — Role dedup must not collapse distinct roles (L23)
- **Historical fix:** `4bff7c7` "Tighten role dedup: collapse only provably-identical postings (title+location+JD)"
- **Files:** `backend/app/services/discovery.py`
- **Symptom:** Discovery drops genuinely distinct roles that share a generic title.
  Google has several different "Strategy and Operations Lead" roles (different orgs,
  levels, locations); a title-only dedup key keeps only the first and silently loses
  the rest. Also, two different roles with the same title AND same location (e.g. two
  "Product Manager" postings in Mountain View with different JDs) must BOTH be kept.
  Only a true repost — same title, same location, same JD text — should collapse.
- **Grade:** `L23-dedup-title-location` (behavioral: imports `_dedup_key`, asserts
  different-location keeps both, different-JD keeps both, reordered-city repost collapses).

### B2 — Amazon discovery returning ~0 jobs (L25)
- **Historical fix:** `c961c63` "Fix Amazon fetch returning ~0 jobs (httpx gzip decompressor reuse)"
- **Files:** `backend/app/services/ats_clients.py`
- **Symptom:** `fetch_amazon_jobs()` returns near-zero roles every run. The httpx
  client is reused across the Amazon query loop and Amazon responds gzip; reusing
  one client across gzip responses raises a decompressor-reuse error on every query,
  so Amazon discovery silently collapses to ~0.
- **Grade:** `L25-amazon-accept-encoding-identity` (asserts the header fix inside
  `fetch_amazon_jobs`' request block).

### B3 — Scoring must be deterministic (L26)
- **Historical fix:** `553cfd4` "Score at temperature=0 for deterministic, reproducible grading"
- **Files:** `backend/app/services/scoring.py`
- **Symptom:** Running the same role through `score_role()` twice gives different
  scores — sometimes enough to flip a role across the Good/Strong boundary. Default
  temperature makes grading non-reproducible.
- **Grade:** `L26-scoring-temperature-zero` (asserts `temperature=0` on the scoring
  `messages.create` call).

### B4 — Amazon Principal+ roles must be filtered at the source (L20)
- **Historical fix:** `2aed5b5` "Exclude Amazon Principal+ roles from matches (level-up, not realistic internal transfer)"
- **Files:** `backend/app/services/ats_clients.py`
- **Symptom:** Amazon Principal / Director / VP roles appear as Strong/Perfect matches.
  Internal-transfer scoring lifts the big-company cap, which inflates these out-of-reach
  level-up titles. They must be excluded during fetch — never reach scoring. The filter
  must block "Principal Product Manager Technical" / "Principal Worldwide GTM Specialist"
  / "Director, Product Management" but let "Senior Product Manager, AWS" / "PMT-ES, Bedrock"
  / "Worldwide Specialist, GenAI" through.
- **Grade:** `L20-amazon-level-up-filter` (behavioral: asserts the regex blocks
  Principal/Director and passes Senior/PMT titles).

### B5 — Google Careers JD leak + dedup must query live roles (L27)
- **Historical fix:** `f2143fe` "Strip leaked job-id artifact from Google careers JD + dedup live-only"
- **Files:** `backend/app/services/ats_clients.py`, `backend/app/services/discovery.py`
- **Symptom:** Parsed Google careers JDs start with a leaked HTML `<li>` tag remnant
  (` ssk='id'>`) that embeds the job id. That pollutes the scorer input AND the dedup
  fingerprint, so reposts of the same job look unique and get re-inserted. The tag
  remnant must be stripped from `raw_jd`, and dedup must compare against existing
  live roles only.
- **Grade:** `L27-google-careers-jd-clean` (behavioral: feeds a real card HTML with
  `ssk='...id...'` and asserts the parsed `raw_jd` contains no leaked id).

### B6 — Two-axis matching: deterministic conversion tier (L30)
- **Historical fix:** `9b3882b` "Two-axis matching: add deterministic conversion (callback-likelihood) axis"
- **Files:** new `backend/app/services/conversion.py`; edit `backend/app/routes/roles.py`,
  `backend/app/services/notifications.py`
- **Symptom:** Fit score and "will Sam actually get a call" are conflated in the LLM
  fit score, which is noisy. The digest needs a separate deterministic
  `conversion_tier` (high/low) computed from title archetypes, independent of the LLM
  score. Titles like "Head of Competitive Intelligence", "Strategy and Operations Lead",
  "Sr. Worldwide GTM Specialist, Agentic AI", "Group Product Manager, 0-1 AI Products"
  are HIGH; "Product Manager, Google Images, Search" and "Group Product Manager, Ads"
  are LOW. `GET /roles` must expose it; the digest must rank by it.
- **Grade:** `L30-conversion-axis` (behavioral: imports `conversion_tier`, asserts
  high/low per archetype; also asserts routes/notifications wiring).

---

## Task selection notes

- **Avoid these as first-run tasks:** B2/B5 touch external-fetch code paths whose full
  validation needs network; the selfcheck assertions are still deterministic string/
  behavioral checks, so they grade fine offline, but don't add live-run expectations.
- **Frontend tasks are weaker grading** — no test framework exists (`frontend` has no
  jest/playwright), so UI changes (e.g. hide-Possible-Match, conversion badge) can only
  be graded by build (`npm --prefix frontend run build`) + manual diff review. Add them
  only after the backend suite is passing.
- **DB-touching tasks** (L7, L20-db) are excluded from the base suite — they need
  Supabase env; run with `--db` only if you want live-data grading.
- **Suggested order:** B3 (tiny) → B1 → B4 → B6 (new module, bigger) → B2 → B5.
  Escalate difficulty; record each result before moving on.
