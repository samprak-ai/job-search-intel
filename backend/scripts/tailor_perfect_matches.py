"""Bulk-generate tailored application packages for all current Anthropic Perfect Matches.

Run locally (requires access to /Users/Sam/Desktop/samresume/).

Usage:
  cd backend
  venv/bin/python scripts/tailor_perfect_matches.py

What it does:
  - Queries Supabase for all live Anthropic roles with score >= 90
  - Skips roles already submitted (Partner Systems, Research PM)
  - Skips roles that already have a package folder
  - Calls generate_anthropic_package() for each remaining role
  - Writes output to /Users/Sam/Desktop/samresume/anthropic/perfect_matches/{slug}/

Safe to re-run: existing package folders are detected and skipped unless --force
is passed.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_supabase_client
from app.services.application_tailor import (
    generate_anthropic_package,
    OUTPUT_DIR,
    _slugify,
)


SUBMITTED_GREENHOUSE_IDS = {
    "5191437008",  # Partner Business Systems & AI Operations Lead
    "5123082008",  # Product Management, Research
}


def normalize_company(s: str) -> str:
    return "".join(c.lower() for c in (s or "") if c.isalnum())


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate packages even if the output folder already exists.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=90,
        help="Minimum overall_score to include (default: 90 = Perfect Match)",
    )
    args = parser.parse_args()

    sb = get_supabase_client()

    # Fetch all roles (paginated)
    all_roles = []
    offset = 0
    while True:
        r = sb.table("roles").select("id, company, title, url, is_live").range(offset, offset + 999).execute()
        if not r.data:
            break
        all_roles.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000

    # Fetch all scores
    all_scores = []
    offset = 0
    while True:
        s = sb.table("role_scores").select("role_id, overall_score").range(offset, offset + 999).execute()
        if not s.data:
            break
        all_scores.extend(s.data)
        if len(s.data) < 1000:
            break
        offset += 1000
    score_map = {s["role_id"]: s for s in all_scores}

    # Select Anthropic Perfect Matches
    targets = []
    seen_title_norm = set()
    for role in all_roles:
        if role.get("is_live") is False:
            continue
        if normalize_company(role["company"]) != "anthropic":
            continue
        if any(sid in role["url"] for sid in SUBMITTED_GREENHOUSE_IDS):
            continue
        score = score_map.get(role["id"])
        if not score or score["overall_score"] < args.min_score:
            continue
        # Skip engineer / solutions architect titles
        tl = role["title"].lower()
        if any(kw in tl for kw in ["engineer", "engineering", "solutions architect"]):
            continue
        # Dedupe by title
        norm = re.sub(r"[^a-z0-9]+", "", tl)[:50]
        if norm in seen_title_norm:
            continue
        seen_title_norm.add(norm)
        targets.append((score["overall_score"], role["title"], role["id"]))

    targets.sort(reverse=True)

    print(f"Found {len(targets)} Anthropic Perfect Match roles to potentially tailor.")
    print()

    generated = 0
    skipped_existing = 0
    errors = 0

    for i, (score, title, rid) in enumerate(targets, 1):
        slug = _slugify(title)
        output_dir = OUTPUT_DIR / slug
        if output_dir.exists() and not args.force:
            print(f"[{i}/{len(targets)}] SKIP (already exists)  {score}  {title[:70]}")
            skipped_existing += 1
            continue

        print(f"[{i}/{len(targets)}] GENERATE  {score}  {title[:70]}")
        try:
            result = await generate_anthropic_package(rid)
            if result["status"] == "generated":
                print(f"              -> {result['output_dir']}")
                generated += 1
            else:
                print(f"              -> {result['status']}: {result.get('reason')}")
        except Exception as e:
            print(f"              -> ERROR: {e}")
            errors += 1

        await asyncio.sleep(0.5)

    print()
    print("=" * 60)
    print(f"Generated:          {generated}")
    print(f"Skipped (existing): {skipped_existing}")
    print(f"Errors:             {errors}")


if __name__ == "__main__":
    asyncio.run(main())
