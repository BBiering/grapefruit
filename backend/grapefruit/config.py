from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # External APIs.
    eodhd_api_key: str = ""
    perplexity_api_key: str = ""

    # Supabase Postgres connection string. Use the Session pooler URI
    # (port 5432). Direct connection is IPv6-only; Cloud Run egress is dual-stack
    # by default but the pooler is more forgiving.
    database_url: str = ""


settings = Settings()
