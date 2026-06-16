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


# ── L10: freshness must not treat 403 as a dead posting ─────────────────────
@check("L10-freshness-403-not-dead")
def _l10():
    fresh = _read(BACKEND / "app/services/freshness.py")
    m = re.search(r"DEAD_STATUSES\s*=\s*\{([^}]*)\}", fresh)
    if m and "403" in m.group(1):
        return ["freshness DEAD_STATUSES includes 403 — 403 is rate-limit/bot-block, not a removed posting (it false-deletes live roles in a burst sweep)"]
    return []


# ── L11: every hardcoded Claude model id must be a current one ──────────────
# A retired snapshot (claude-sonnet-4-20250514) 404'd across 10 files and broke
# all scoring. Keep this set current when models change (see the claude-api skill).
ALLOWED_MODELS = {
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-fable-5",
}


@check("L18-model-ids-current")
def _l11():
    problems = []
    for f in sorted((BACKEND / "app").rglob("*.py")):
        for mid in re.findall(r'model\s*=\s*["\']([^"\']+)["\']', _read(f)):
            if mid.startswith("claude") and mid not in ALLOWED_MODELS:
                problems.append(f'{f.relative_to(BACKEND)}: stale/unknown model id "{mid}"')
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


# ── L11: reviewer must hard-block on groundedness; AI-tell lexicon present ──
@check("L11-reviewer-groundedness-hardblock")
def _l11():
    problems = []
    reviewer = _read(BACKEND / "app/services/reviewer.py")
    if '= "block"' not in reviewer:
        problems.append("reviewer.py: no 'block' verdict path found")
    if "blocking_reasons" not in reviewer:
        problems.append("reviewer.py: missing blocking_reasons aggregation")
    if "def grade_groundedness" not in reviewer:
        problems.append("reviewer.py: missing grade_groundedness grader")
    if "groundedness: unsupported" not in reviewer:
        problems.append("reviewer.py: groundedness failures must add a blocking reason")
    ai = _read(BACKEND / "app/services/agents/ai_tells.py")
    if "LEXICON" not in ai or "def scan_ai_tells" not in ai:
        problems.append("ai_tells.py: missing LEXICON or scan_ai_tells")
    main_py = _read(BACKEND / "app/main.py")
    if "review.router" not in main_py:
        problems.append("main.py: /review router not registered")
    return problems


# ── L12: quick-apply digest is generate-only, grounded, bounded, and wired ──
@check("L12-quick-apply-generate-only-grounded")
def _l12():
    problems = []
    qa = _read(BACKEND / "app/services/quick_apply.py")
    if "def run_quick_apply" not in qa:
        problems.append("quick_apply.py: missing run_quick_apply")
    if "quick_apply_max" not in qa:
        problems.append("quick_apply.py: output must be bounded by quick_apply_max")
    if "ABSOLUTE GROUNDING RULE" not in qa:
        problems.append("quick_apply.py: grounding rule missing from generation prompt")
    if "LOCKED_IN_FACTS_MARKDOWN" not in qa:
        problems.append("quick_apply.py: must inject locked-in facts into the prompt")
    main_py = _read(BACKEND / "app/main.py")
    if "quick_apply.router" not in main_py:
        problems.append("main.py: /quick-apply router not registered")
    disc = _read(BACKEND / "app/routes/discover.py")
    if "run_quick_apply()" not in disc:
        problems.append("discover.py: quick-apply not folded into the daily cron")
    if "cron_enable_quick_apply" not in disc:
        problems.append("discover.py: quick-apply must respect the cron_enable_quick_apply toggle")
    return problems


# ── L13: accuracy guards — "12+ years" qualified; no LinkedIn-as-source ──
@check("L13-accuracy-claim-guards")
def _l13():
    problems = []
    rev = _read(BACKEND / "app/services/reviewer.py")
    if "must be qualified as total experience" not in rev:
        problems.append("reviewer.py: missing '12+ years' overclaim guard")
    if "LinkedIn cited as a source" not in rev:
        problems.append("reviewer.py: missing LinkedIn-as-source guard")
    prof = _read(BACKEND / "config/profile.json")
    for bad in ["12+ years GTM", "GTM + Sales Ops", "12+ years driving", "and LinkedIn"]:
        if bad in prof:
            problems.append(f'profile.json still contains the overclaim/source "{bad}"')
    return problems


# ── L14: Amazon discovery/scoring calibrated to Sam's saved-roles signal ──
@check("L14-amazon-saved-roles-calibration")
def _l14():
    problems = []
    ats = _read(BACKEND / "app/services/ats_clients.py")
    if '"Partner Specialist"' not in ats:
        problems.append("ats_clients.py: AMAZON_BASE_QUERIES missing 'Partner Specialist'")
    if "partner specialist" not in ats:
        problems.append("ats_clients.py: ROLE_KEYWORDS missing 'partner specialist'")
    adj = _read(BACKEND / "config/scoring_adjustments.json")
    if '"Amazon"' not in adj:
        problems.append("scoring_adjustments.json: missing Amazon company_note calibration")
    return problems


# ── L15: reviewer carries an Amazon writing-style lint (weasel words, we/our) ──
@check("L15-amazon-style-lint")
def _l15():
    problems = []
    rev = _read(BACKEND / "app/services/reviewer.py")
    if "AMAZON_WEASEL" not in rev:
        problems.append("reviewer.py: missing AMAZON_WEASEL list")
    if "Amazon style: weasel word" not in rev:
        problems.append("reviewer.py: missing Amazon weasel-word lint")
    if "prefer 'I' over 'we/our'" not in rev:
        problems.append("reviewer.py: missing Amazon we/our self-assessment lint")
    return problems


# ── L16: AI-products framing (substance-first; non-engineer is AI-labs-only) ──
@check("L16-ai-products-framing")
def _l16():
    problems = []
    lf = _read(BACKEND / "app/services/agents/locked_facts.py")
    if "Framing the AI products" not in lf:
        problems.append("locked_facts.py: missing AI-products framing guideline")
    rev = _read(BACKEND / "app/services/reviewer.py")
    if "lead with the engineering substance" not in rev:
        problems.append("reviewer.py: missing AI-products framing lint")
    if "drop the non-engineer" not in rev:
        problems.append("reviewer.py: missing Amazon non-engineer-drop lint")
    return problems


# ── L17: Amazon-internal performance language must stay off external artifacts ──
@check("L17-amazon-internal-language-external-guard")
def _l17():
    problems = []
    rev = _read(BACKEND / "app/services/reviewer.py")
    if "Amazon-internal performance language on a non-Amazon artifact" not in rev:
        problems.append("reviewer.py: missing Amazon-internal-language external guard")
    # behavioral: phrase must be a must_fix for an external company, silent for Amazon
    try:
        from app.services.reviewer import deterministic_review
        sample = "Annual review: Exceeds High Bar for two consecutive years."
        ext = deterministic_review(sample, company="OpenAI")["format"]
        amz = deterministic_review(sample, company="Amazon")["format"]
        if not ext["must_fix"]:
            problems.append("guard did not must_fix 'Exceeds High Bar' on an external artifact")
        if any("Amazon-internal" in f["rule"] for f in amz["flags"]):
            problems.append("guard wrongly flagged 'Exceeds High Bar' on an Amazon artifact")
    except Exception as e:  # pragma: no cover
        problems.append(f"L17 behavioral check errored: {e}")
    return problems


# ── L19: email application-update bridge uses the single outcome write path ──
# The inbox->outcome->Forge bridge must NOT fork outcome state: it writes through
# services.outcomes.record_outcome() (same as PATCH /roles), never INSERTs
# application_outcomes directly. It must also stay bounded, idempotent, fire
# Forge on positive movement, and ignore this app's own digests.
@check("L19-application-updates-bridge-single-write-path")
def _l19():
    problems = []
    svc_path = BACKEND / "app/services/application_updates.py"
    if not svc_path.exists():
        return ["app/services/application_updates.py is missing"]
    svc = _read(svc_path)
    if "def ingest_updates" not in svc:
        problems.append("application_updates.py: missing ingest_updates entry point")
    if "record_outcome(" not in svc:
        problems.append("application_updates.py: must write through record_outcome() (single return path)")
    if 'table("application_outcomes")' in svc or "table('application_outcomes')" in svc:
        problems.append("application_updates.py: must NOT write application_outcomes directly (forks outcome state — see M5)")
    if "MAX_EMAILS_PER_RUN" not in svc:
        problems.append("application_updates.py: ingestion must be bounded by MAX_EMAILS_PER_RUN")
    if "generate_session_config" not in svc:
        problems.append("application_updates.py: positive movement must fire Forge (generate_session_config)")
    if "email_application_updates" not in svc or "message_id" not in svc:
        problems.append("application_updates.py: missing message_id idempotency via email_application_updates")
    if "onboarding@resend.dev" not in svc:
        problems.append("application_updates.py: must ignore this app's own digest sender")
    main_py = _read(BACKEND / "app/main.py")
    if "application_updates.router" not in main_py:
        problems.append("main.py: /application-updates router not registered")
    return problems


# ── L20: Amazon Principal+ roles are filtered out (level-up, not realistic) ──
# Internal transfers rarely clear a level jump, so Principal/Director/VP Amazon
# roles must be excluded at the source before they reach scoring — otherwise the
# internal-transfer scoring lift inflates them to Perfect/Strong matches.
@check("L20-amazon-level-up-filter")
def _l20():
    problems = []
    ats = _read(BACKEND / "app/services/ats_clients.py")
    if "AMAZON_LEVEL_UP_RE" not in ats:
        problems.append("ats_clients.py: missing AMAZON_LEVEL_UP_RE level-up filter")
    if "if AMAZON_LEVEL_UP_RE.search(title):" not in ats:
        problems.append("ats_clients.py: fetch_amazon_jobs must skip level-up titles")
    # behavioral: the regex must catch Principal and pass Senior/PMT
    try:
        from app.services.ats_clients import AMAZON_LEVEL_UP_RE
        for blocked in ("Principal Product Manager Technical, AgentCore",
                        "Principal Worldwide GTM Specialist - GenAI",
                        "Director, Product Management"):
            if not AMAZON_LEVEL_UP_RE.search(blocked):
                problems.append(f"L20 regex failed to block level-up title: {blocked!r}")
        for allowed in ("Senior Product Manager, AWS", "PMT-ES, Bedrock",
                        "Worldwide Specialist, GenAI"):
            if AMAZON_LEVEL_UP_RE.search(allowed):
                problems.append(f"L20 regex wrongly blocked in-band title: {allowed!r}")
    except Exception as e:  # pragma: no cover
        problems.append(f"L20 behavioral check errored: {e}")
    return problems


@check("L20-no-amazon-principal-matches", kind="db")
def _l20_db():
    """No Amazon Principal+ role should be sitting in the live match list."""
    from app.config import get_supabase_client
    sb = get_supabase_client()
    roles = (
        sb.table("roles").select("id,title").eq("company", "Amazon").execute().data
    )
    import re as _re
    lvl = _re.compile(r"\b(principal|director|vice president|\bvp\b)\b", _re.IGNORECASE)
    offenders = [r for r in roles if lvl.search(r.get("title") or "")]
    if not offenders:
        return []
    return [f"{len(offenders)} Amazon Principal+ role(s) still tracked, e.g. {offenders[0]['title']!r}"]


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
