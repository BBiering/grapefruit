from fastapi import APIRouter
from pydantic import BaseModel, Field

from grapefruit.candidates import CandidateParams, scan_candidates

router = APIRouter()


class CandidateBody(BaseModel):
    lookback_days: int = Field(default=20, ge=2, le=252)
    gain_pct: float = Field(default=1.0, ge=0.0)
    vol_mult: float = Field(default=2.0, ge=1.0)
    high_lookback: int = Field(default=60, ge=5, le=252)
    limit: int = Field(default=100, ge=1, le=500)


@router.post("/api/candidates/scan")
def candidates_scan(body: CandidateBody) -> list[dict]:
    params = CandidateParams(
        lookback_days=body.lookback_days,
        gain_pct=body.gain_pct,
        vol_mult=body.vol_mult,
        high_lookback=body.high_lookback,
    )
    return scan_candidates(params, limit=body.limit)
