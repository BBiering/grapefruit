from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from grapefruit.api import routes_candidates, routes_jobs, routes_scan, routes_tickers
from grapefruit.storage import init_db

app = FastAPI(title="Grapefruit", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_scan.router)
app.include_router(routes_tickers.router)
app.include_router(routes_candidates.router)
app.include_router(routes_jobs.router)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
