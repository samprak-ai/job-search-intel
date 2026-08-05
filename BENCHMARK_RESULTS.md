# Benchmark Results — DeepSeek V4 Flash (Zen free) on opencode

Date: 2026-08-05
Candidate: opencode/deepseek-v4-flash-free
Baseline: repo HEAD (af8a846), `backend/selfcheck.py` static checks.
Note: baseline is fully green at HEAD — the pending working-tree scoring fixes
were committed (af8a846) before B2/B5 ran.

## Results

| Task | Guard | Candidate fix | Grading | Result |
|------|-------|---------------|---------|--------|
| B1 — role dedup over-collapses distinct roles | L23 | `_dedup_key(title, location, raw_jd)` with `_jd_fingerprint()` (300-char normalized JD prefix); dedup DB queries now select `raw_jd` + pass it through both ATS and LinkedIn paths | L23 PASS on fix, FAIL on revert, PASS on restore | ✅ PASS |
| B3 — scoring non-deterministic (flips Good/Strong) | L26 | `temperature=0` on the scoring `messages.create` call | L26 PASS | ✅ PASS |
| B4 — Amazon Principal+ roles inflate to Strong/Perfect | L20 | `AMAZON_LEVEL_UP_RE` (`\b(principal|director|vice president|\bvp\b)\b`, IGNORECASE) + skip in `fetch_amazon_jobs`; behavioral block/pass titles verified | L20 PASS | ✅ PASS |
| B6 — fit ≠ callback-likelihood; add conversion axis | L30 | New `services/conversion.py` (`conversion_tier` high/medium/low + `TIER_RANK`); digest sorts by (conversion, fit); `GET /roles` exposes `conversion` field; email badge | L30 PASS | ✅ PASS |
| B2 — Amazon discovery returning ~0 jobs (gzip) | L25 | `"Accept-Encoding": "identity"` in the `fetch_amazon_jobs` request headers | L25 FAIL on revert, PASS on fix | ✅ PASS |
| B5 — Google careers JD leak + dedup live-only | L27 | `card = re.sub(r"^[^>]*>", "", card, count=1)` in `_parse_google_careers`; `.eq("is_live", True)` on both dedup lookups (`discover_via_ats`, `discover_via_linkedin`) | L27 FAIL on revert, PASS on fix | ✅ PASS |

## Verification strength

- **B1, B4, B6, B5** graded by selfcheck checks with embedded behavioral unit tests
  (import the code, assert on behavior) — not just string greps.
- **B3** graded by a deterministic static assertion (`temperature=0` in the call).
- **B2** graded by a deterministic static assertion (header present in the fetch block).
- All fixes were reverted-in-a-worktree first and confirmed the guard FAILS before
  the candidate's edit and PASSES after.

## Candidate diff quality vs historical fixes

- **B1**: functionally identical to `4bff7c7`; only docstring phrasing differs.
- **B3**: functionally identical to `553cfd4`; only comment placement differs.
- **B4**: byte-identical to `2aed5b5` (worktree diff vs HEAD was empty).
- **B6**: byte-identical to `9b3882b` (worktree diff vs HEAD was empty).
- **B2**: functionally identical to `c961c63` (same `Accept-Encoding: identity` line); only the explanatory comment is shorter.
- **B5**: byte-identical to `f2143fe` (worktree diff vs HEAD was empty).

## Verdict — backend suite complete

All six backend benchmark tasks pass (B1–B6). DeepSeek V4 Flash (Zen free) on
opencode reproduced the historical Claude-Opus fixes — four functionally or
byte-identical, two byte-identical. The selfcheck harness runs green at HEAD
after every fix. This clears the quality gate for the **dev-workflow** swap;
runtime AI (scoring/intel inference) remains on Claude by design and would need
separate validation via the app's own `application_outcomes` calibration loop.

## Follow-ups

- Frontend tasks excluded (no test framework in `frontend/`).
- B2/B5 live-network validation (actual gzip responses, real Google cards) would
  add confidence beyond the offline behavioral guards; defer unless needed.
- Runtime-AI swap (scoring/intel to DeepSeek) remains a separate decision — validate
  via `application_outcomes` calibration before flipping. Not part of this gate.
