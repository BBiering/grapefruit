from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # External APIs
    eodhd_api_key: str = ""
    perplexity_api_key: str = ""

    # Supabase Postgres connection string (postgresql://...).
    database_url: str = ""

    # Comma-separated list of allowed CORS origins (Vercel URL + custom domain).
    # Local dev origins are always allowed regardless of this value.
    frontend_origin: str = ""


settings = Settings()
