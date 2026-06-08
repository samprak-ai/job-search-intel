"""Stage 2: Persona loader.

Reads Sam's source-of-truth profile (profile.json + sam-profile.md interview
narrative + locked-in facts) into a single structured dict. Cached on disk
with mtime invalidation so we don't re-read on every pipeline run.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from app.config import load_profile
from app.services.agents.locked_facts import LOCKED_IN_FACTS_MARKDOWN

logger = logging.getLogger(__name__)

# Interview/positioning narrative lives in samresume repo
SAM_PROFILE_MD = Path("/Users/Sam/Desktop/samresume/_context/sam-profile.md")


def _read_narrative() -> str:
    if not SAM_PROFILE_MD.exists():
        logger.warning(f"sam-profile.md not found at {SAM_PROFILE_MD}")
        return ""
    try:
        return SAM_PROFILE_MD.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read sam-profile.md: {e}")
        return ""


def _narrative_mtime() -> float:
    if not SAM_PROFILE_MD.exists():
        return 0.0
    return SAM_PROFILE_MD.stat().st_mtime


@lru_cache(maxsize=1)
def _cached_persona(narrative_mtime: float) -> dict:
    """Inner cache keyed on the narrative's mtime so file edits invalidate."""
    profile = load_profile()
    narrative = _read_narrative()
    return {
        "profile_json": profile,
        "interview_narrative": narrative,
        "locked_in_facts": LOCKED_IN_FACTS_MARKDOWN,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "narrative_mtime": narrative_mtime,
    }


def load_persona() -> dict:
    """Return the persona artifact. Cached per-process, mtime-invalidated."""
    return _cached_persona(_narrative_mtime())


def persona_snapshot(persona: dict) -> dict:
    """Lightweight snapshot for DB storage (drops the heavy narrative text)."""
    return {
        "loaded_at": persona["loaded_at"],
        "narrative_mtime": persona["narrative_mtime"],
        "profile_fields": sorted(persona["profile_json"].keys()),
        "narrative_length": len(persona["interview_narrative"]),
    }
