import json
import os
from pathlib import Path
from functools import lru_cache

from dotenv import dotenv_values
from supabase import create_client, Client

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"


def _env_get(key: str, default: str = "") -> str:
    """Read from .env file first, fall back to os.environ (for Railway/production)."""
    return _dotenv_cache().get(key) or os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    value = _env_get(key, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    value = _env_get(key, str(default)).strip()
    try:
        return int(value)
    except ValueError:
        return default


@lru_cache
def _dotenv_cache() -> dict:
    env_path = BACKEND_DIR / ".env"
    if env_path.exists():
        return dotenv_values(env_path)
    return {}


@lru_cache
def get_settings():
    """Load settings from .env file (local) or os.environ (Railway/production)."""

    class Settings:
        supabase_url: str = _env_get("SUPABASE_URL")
        # Prefer the service_role key (server-side only — bypasses RLS) so we can
        # enable Row-Level Security on every table and lock out the public anon
        # key. Falls back to SUPABASE_KEY (anon) so nothing breaks before the
        # service key is set in the environment.
        supabase_key: str = _env_get("SUPABASE_SERVICE_KEY", "") or _env_get("SUPABASE_KEY")
        anthropic_api_key: str = _env_get("ANTHROPIC_API_KEY")
        serper_api_key: str = _env_get("SERPER_API_KEY")
        brave_api_key: str = _env_get("BRAVE_API_KEY")
        search_provider: str = _env_get("SEARCH_PROVIDER", "brave")
        serper_daily_limit: int = _env_int("SERPER_DAILY_LIMIT", 25)
        cron_enable_role_discovery: bool = _env_bool("CRON_ENABLE_ROLE_DISCOVERY", False)
        resend_api_key: str = _env_get("RESEND_API_KEY")
        notification_email: str = _env_get("NOTIFICATION_EMAIL")
        cron_secret: str = _env_get("CRON_SECRET")
        cron_companies: str = _env_get("CRON_COMPANIES")  # comma-separated list
        frontend_url: str = _env_get("FRONTEND_URL")
        forge_api_url: str = _env_get("FORGE_API_URL")
        forge_import_key: str = _env_get("FORGE_IMPORT_KEY")

    return Settings()


@lru_cache
def get_supabase_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_key)


def load_profile() -> dict:
    with open(CONFIG_DIR / "profile.json") as f:
        return json.load(f)


def load_companies() -> list[dict]:
    with open(CONFIG_DIR / "companies.json") as f:
        return json.load(f)["target_companies"]


def load_scoring_adjustments() -> dict:
    """Approved calibration notes from the reflection loop, fed into scoring.

    Merges two sources:
      1. config/scoring_adjustments.json — optional manual / versioned override.
      2. scoring_adjustments table — persistent, written by one-click "approve"
         (the Railway filesystem is ephemeral, so the DB is the durable store).

    Shape: {"global_notes": [str], "company_notes": {company: [str]}}.
    Never raises — scoring must not break on a bad source.
    """
    global_notes: list[str] = []
    company_notes: dict[str, list[str]] = {}

    # 1. File override
    try:
        with open(CONFIG_DIR / "scoring_adjustments.json") as f:
            data = json.load(f)
        global_notes.extend(data.get("global_notes", []) or [])
        for company, notes in (data.get("company_notes", {}) or {}).items():
            company_notes.setdefault(company, []).extend(notes or [])
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 2. Approved rows from the DB
    try:
        rows = (
            get_supabase_client()
            .table("scoring_adjustments")
            .select("scope, note")
            .eq("active", True)
            .execute()
            .data
            or []
        )
        for r in rows:
            scope = (r.get("scope") or "").strip()
            note = r.get("note")
            if not note:
                continue
            if scope.lower() == "global":
                global_notes.append(note)
            elif scope:
                company_notes.setdefault(scope, []).append(note)
    except Exception:  # DB unreachable / table missing — fall back to file only
        pass

    return {"global_notes": global_notes, "company_notes": company_notes}
