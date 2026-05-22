from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
NEWS_CACHE_DIR = DATA_DIR / "news_cache"
NEWS_CACHE_DIR.mkdir(exist_ok=True)
CATALYST_CACHE_DIR = DATA_DIR / "catalyst_cache"
CATALYST_CACHE_DIR.mkdir(exist_ok=True)
DUCKDB_PATH = DATA_DIR / "bars.duckdb"
UNIVERSE_PATH = DATA_DIR / "universe.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    apca_api_key_id: str = ""
    apca_api_secret_key: str = ""
    perplexity_api_key: str = ""
    finnhub_api_key: str = ""


settings = Settings()
