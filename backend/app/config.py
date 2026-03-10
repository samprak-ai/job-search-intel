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
        supabase_key: str = _env_get("SUPABASE_KEY")
        anthropic_api_key: str = _env_get("ANTHROPIC_API_KEY")
        serper_api_key: str = _env_get("SERPER_API_KEY")
        brave_api_key: str = _env_get("BRAVE_API_KEY")
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
