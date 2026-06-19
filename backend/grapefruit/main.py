import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from grapefruit.api import routes_candidates, routes_jobs, routes_scan, routes_tickers
from grapefruit.config import settings
from grapefruit.storage import init_db


log = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    extra = [o.strip().rstrip("/") for o in settings.frontend_origin.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *extra,
    ]


# Match every grapefruit-*.vercel.app deploy (production + preview branches)
# so the user doesn't have to update FRONTEND_ORIGIN for each preview URL.
_VERCEL_PREVIEW_RE = r"https://grapefruit(-[a-z0-9-]+)?\.vercel\.app"


app = FastAPI(title="Grapefruit", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_origin_regex=_VERCEL_PREVIEW_RE,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_scan.router)
app.include_router(routes_tickers.router)
app.include_router(routes_candidates.router)
app.include_router(routes_jobs.router)


@app.on_event("startup")
def _on_startup() -> None:
    if not settings.database_url:
        log.warning("DATABASE_URL is not set; storage calls will fail until configured")
        return
    try:
        init_db()
    except Exception:  # noqa: BLE001
        log.exception("init_db() failed at startup; backend will return 500s on DB calls")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
