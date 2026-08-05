# Benchmark Results — DeepSeek V4 Flash (Zen free) on opencode

Date: 2026-08-05
Candidate: opencode/deepseek-v4-flash-free
Baseline: repo HEAD (e073fec), `backend/selfcheck.py` static checks.
Note: L28/L29 fail at bare HEAD because uncommitted working-tree scoring fixes
aren't in HEAD — pre-existing, unrelated to any task below.

## Results

| Task | Guard | Candidate fix | Grading | Result |
|------|-------|---------------|---------|--------|
| B1 — role dedup over-collapses distinct roles | L23 | `_dedup_key(title, location, raw_jd)` with `_jd_fingerprint()` (300-char normalized JD prefix); dedup DB queries now select `raw_jd` + pass it through both ATS and LinkedIn paths | L23 PASS on fix, FAIL on revert, PASS on restore | ✅ PASS |
| B3 — scoring non-deterministic (flips Good/Strong) | L26 | `temperature=0` on the scoring `messages.create` call | L26 PASS | ✅ PASS |
| B4 — Amazon Principal+ roles inflate to Strong/Perfect | L20 | `AMAZON_LEVEL_UP_RE` (`\b(principal|director|vice president|\bvp\b)\b`, IGNORECASE) + skip in `fetch_amazon_jobs`; behavioral block/pass titles verified | L20 PASS | ✅ PASS |
| B6 — fit ≠ callback-likelihood; add conversion axis | L30 | New `services/conversion.py` (`conversion_tier` high/medium/low + `TIER_RANK`); digest sorts by (conversion, fit); `GET /roles` exposes `conversion` field; email badge | L30 PASS | ✅ PASS |

## Verification strength

- **B1, B4, B6** graded by selfcheck checks with embedded behavioral unit tests
  (import the code, assert on behavior) — not just string greps.
- **B3** graded by a deterministic static assertion (`temperature=0` in the call).
- All fixes were reverted-in-a-worktree first and confirmed the guard FAILS before
  the candidate's edit and PASSES after.

## Candidate diff quality vs historical fixes

- **B1**: functionally identical to `4bff7c7`; only docstring phrasing differs.
- **B3**: functionally identical to `553cfd4`; only comment placement differs.
- **B4**: byte-identical to `2aed5b5` (worktree diff vs HEAD was empty).
- **B6**: byte-identical to `9b3882b` (worktree diff vs HEAD was empty).

## Follow-ups

- B2 (Amazon gzip) and B5 (Google careers JD leak) still untested — defer (need
  network-adjacent confidence; guards are still offline-gradeable).
- Frontend tasks excluded (no test framework in `frontend/`).
- Re-run after committing the pending working-tree scoring fixes so L28/L29
  baseline is green.
