#!/usr/bin/env python3
"""Self-check harness — deterministic guards against regressions we already fixed.

Each check maps to an entry in LEARNINGS.md. This is the enforcement half of the
self-improvement loop: a gap isn't "guarded" until it has a check here.

- STATIC checks read source files only (no env, no DB, stdlib only) so they run
  fast and offline — suitable for the Claude Code Stop hook and pre-push.
- DB checks (run with --db / --all) require Supabase env; they validate live data
  invariants (e.g. no duplicate score rows).

Exit 0 if all run checks pass, 1 if any fail.

Usage:
    python3 selfcheck.py          # static checks only (default)
    python3 selfcheck.py --db     # static + DB checks
    python3 selfcheck.py --all    # everything
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
REPO = BACKEND.parent

# (id, kind, fn) — fn returns a list of failure strings ([] == pass)
CHECKS: list[tuple[str, str, object]] = []


def check(check_id: str, kind: str = "static"):
    def deco(fn):
        CHECKS.append((check_id, kind, fn))
        return fn
    return deco


def _read(rel: Path) -> str:
    return rel.read_text(encoding="utf-8")


# ── L1: match-tier strings must match between scoring.py and CLAUDE.md ──────
@check("L1-tier-strings-consistent")
def _l1():
    problems = []
    scoring = _read(BACKEND / "app/services/scoring.py")
    m = re.search(r'"match_tier":\s*"([^"]+)"', scoring)
    if not m:
        return ["could not find the match_tier enum line in scoring.py"]
    tiers = [t.strip() for t in m.group(1).split("|")]
    claude = _read(REPO / "CLAUDE.md")
    for t in tiers:
        if t not in claude:
            problems.append(f'CLAUDE.md is missing tier string "{t}"')
    if "Worth Applying" in claude:
        problems.append('CLAUDE.md still references the stale tier "Worth Applying"')
    return problems


# ── L2: notification bar must come from one source, not be hardcoded ────────
@check("L2-notification-bar-single-source")
def _l2():
    problems = []
    notif = _read(BACKEND / "app/services/notifications.py")
    if "def notification_threshold" not in notif:
        problems.append("notifications.py is missing notification_threshold()")
    if "COMPANY_NOTIFICATION_THRESHOLDS" not in notif:
        problems.append("notifications.py is missing COMPANY_NOTIFICATION_THRESHOLDS")
    scoring = _read(BACKEND / "app/services/scoring.py")
    if "notification_threshold(" not in scoring:
        problems.append(
            "scoring.py does not call notification_threshold() — the notify gate may be hardcoded"
        )
    return problems


# ── L3: profile.json must agree with locked_facts.py (drift caused critic FPs) ─
@check("L3-profile-matches-locked-facts")
def _l3():
    problems = []
    profile = _read(BACKEND / "config/profile.json")
    for must in ["600 hours", "70%", "Kiro"]:
        if must not in profile:
            problems.append(f'profile.json is missing locked fact "{must}"')
    for banned in ["480 hours", "Amazon Q Spaces", "Bedrock Agents"]:
        if banned in profile:
            problems.append(f'profile.json contains stale/banned fact "{banned}"')
    return problems


# ── L4: Amazon job URLs must be built from www.amazon.jobs + job_path ────────
@check("L4-amazon-url-construction")
def _l4():
    problems = []
    ats = _read(BACKEND / "app/services/ats_clients.py")
    if "https://www.amazon.jobs" not in ats:
        problems.append("ats_clients.py: Amazon URL base is not https://www.amazon.jobs")
    if "job_path" not in ats:
        problems.append("ats_clients.py: fetch_amazon_jobs not using job_path for the URL")
    return problems


# ── L5: every CRON_COMPANIES name must exist in companies.json ──────────────
@check("L5-cron-companies-valid")
def _l5():
    problems = []
    claude = _read(REPO / "CLAUDE.md")
    m = re.search(r"CRON_COMPANIES=([^\n`]+)", claude)
    if not m:
        return ["CLAUDE.md does not document a CRON_COMPANIES value"]
    names = [n.strip() for n in m.group(1).split(",") if n.strip()]
    companies = json.loads(_read(BACKEND / "config/companies.json"))
    valid = {c["name"] for c in companies.get("target_companies", [])}
    problems += [
        f'CRON_COMPANIES name "{n}" is not in companies.json'
        for n in names if n not in valid
    ]
    # The code default must match the documented cron scope (drift guard).
    disc = _read(BACKEND / "app/routes/discover.py")
    dm = re.search(r"DEFAULT_CRON_COMPANIES\s*=\s*\[([^\]]*)\]", disc)
    if dm:
        defaults = [s.strip().strip("\"'") for s in dm.group(1).split(",") if s.strip()]
        if set(defaults) != set(names):
            problems.append(
                f"DEFAULT_CRON_COMPANIES {defaults} != CLAUDE.md CRON_COMPANIES {names}"
            )
    return problems


# ── L6: Amazon freshness must not treat 403 as dead (bot-throttle trap) ──────
@check("L6-amazon-freshness-403-safe")
def _l6():
    fresh = _read(BACKEND / "app/services/freshness.py")
    if "_check_amazon" not in fresh:
        return ["freshness.py is missing _check_amazon (the 403-safe Amazon check)"]
    return []


# ── L8: every route module must be imported AND registered in main.py ───────
@check("L8-routers-registered")
def _l8():
    routes_dir = BACKEND / "app/routes"
    main = _read(BACKEND / "app/main.py")
    problems = []
    for f in sorted(routes_dir.glob("*.py")):
        mod = f.stem
        if mod == "__init__":
            continue
        if mod not in main:
            problems.append(f'route module "{mod}" is not imported in main.py')
        elif f"{mod}.router" not in main:
            problems.append(f'route module "{mod}" is imported but never include_router()-ed')
    return problems


# ── L9: no migration may DISABLE row-level security ─────────────────────────
@check("L9-no-rls-disabled-in-migrations")
def _l9():
    sql_dir = REPO / "supabase"
    problems = []
    for f in sorted(sql_dir.glob("*.sql")):
        if "DISABLE ROW LEVEL SECURITY" in _read(f).upper():
            problems.append(f"{f.name} disables RLS — public tables must keep RLS enabled")
    return problems


# ── L7 (DB): no role may have more than one role_scores row ──────────────────
@check("L7-no-duplicate-role-scores", kind="db")
def _l7():
    from collections import Counter

    sys.path.insert(0, str(BACKEND))
    from app.config import get_supabase_client

    sb = get_supabase_client()
    rows = sb.table("role_scores").select("role_id").execute().data or []
    counts = Counter(r["role_id"] for r in rows)
    dups = [rid for rid, n in counts.items() if n > 1]
    return [f"{len(dups)} role(s) have duplicate role_scores rows: {dups[:5]}"] if dups else []


def main() -> int:
    args = set(sys.argv[1:])
    run_db = bool(args & {"--db", "--all"})

    failures = 0
    for check_id, kind, fn in CHECKS:
        if kind == "db" and not run_db:
            print(f"SKIP {check_id} (db check — pass --db to run)")
            continue
        try:
            problems = fn()
        except Exception as e:  # a broken check is itself a failure
            problems = [f"check raised {type(e).__name__}: {e}"]
        if problems:
            failures += 1
            print(f"FAIL {check_id}")
            for p in problems:
                print(f"       - {p}")
        else:
            print(f"PASS {check_id}")

    print()
    if failures:
        print(f"❌ {failures} self-check(s) FAILED — see LEARNINGS.md for the invariant.")
        return 1
    print("✅ All self-checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
