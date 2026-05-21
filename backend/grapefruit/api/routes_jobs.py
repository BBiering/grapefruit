from fastapi import APIRouter, HTTPException

from grapefruit.jobs import get_job, list_jobs

router = APIRouter()


@router.get("/api/jobs")
def jobs_index() -> list[dict]:
    return list_jobs()


@router.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.to_dict()
