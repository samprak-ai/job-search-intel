#!/usr/bin/env python3
"""A/B scoring harness: Claude (current) vs DeepSeek (candidate) on the same JDs.

Runs the SAME scoring prompt through both providers, parses both JSON responses,
and prints a side-by-side comparison. For the runtime-swap calibration gate.

Usage:
    ./venv/bin/python scripts/ab_score.py <postings.json> [--notify-email] 

postings.json = list of role dicts, each with:
    title, company, location, source, url, raw_jd

Requires (in backend/.env or env): ANTHROPIC_API_KEY, DEEPSEEK_API_KEY.
DeepSeek endpoint + model configurable via DEEPSEEK_BASE_URL / DEEPSEEK_MODEL.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.services.scoring import SCORING_SYSTEM_PROMPT, build_scoring_message  # noqa: E402
from app.config import load_profile  # noqa: E402

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
CLAUDE_MODEL = os.getenv("AB_CLAUDE_MODEL", "claude-sonnet-4-6")


def _call_anthropic(system: str, user: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip()


def _call_deepseek(system: str, user: str) -> str:
    resp = httpx.post(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
        json={
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _parse_score(text: str) -> dict:
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _tier(score: int) -> str:
    if score >= 90:
        return "Perfect Match"
    if score >= 80:
        return "Strong Match"
    if score >= 70:
        return "Good Match"
    if score >= 60:
        return "Possible Match"
    return "Unlikely Match"


def main(path: str) -> int:
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("Missing ANTHROPIC_API_KEY in backend/.env")
        return 1
    if "DEEPSEEK_API_KEY" not in os.environ:
        print("Missing DEEPSEEK_API_KEY in backend/.env (set it before running)")
        return 1

    postings = json.loads(Path(path).read_text())
    profile = load_profile()
    agree = 0

    print(f"Claude: {CLAUDE_MODEL} | DeepSeek: {DEEPSEEK_MODEL}\n")
    for i, role in enumerate(postings, 1):
        user = build_scoring_message(role, profile)
        try:
            claude_text = _call_anthropic(SCORING_SYSTEM_PROMPT, user)
            ds_text = _call_deepseek(SCORING_SYSTEM_PROMPT, user)
            c = _parse_score(claude_text)
            d = _parse_score(ds_text)
        except Exception as e:
            print(f"[{i}] {role['title']} — ERROR: {e}")
            continue

        ct, cs = c.get("match_tier"), c.get("overall_score")
        dt, ds = d.get("match_tier"), d.get("overall_score")
        same = ct == dt and abs((cs or 0) - (ds or 0)) <= 2
        agree += 1 if same else 0
        flag = "MATCH" if same else "DIFF"
        print(f"[{i}] {flag} — {role['company']} | {role['title']}")
        print(f"    Claude   : {cs} {ct}  | ds=({c.get('dimension_scores', {})})")
        print(f"    DeepSeek : {ds} {dt}  | ds=({d.get('dimension_scores', {})})")
        if not same:
            print(f"    Claude rationale  : {c.get('rationale','')[:300]}")
            print(f"    DeepSeek rationale: {d.get('rationale','')[:300]}")
        print()

    print(f"Agreement: {agree}/{len(postings)} (tier + within 2pts)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
