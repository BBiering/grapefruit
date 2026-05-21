import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class JobState:
    job_id: str
    kind: str
    status: str = "pending"  # pending | running | done | error
    processed: int = 0
    total: int = 0
    message: str = ""
    result: Any | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "processed": self.processed,
            "total": self.total,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
        }


_jobs: dict[str, JobState] = {}
_lock = threading.Lock()


def new_job(kind: str) -> JobState:
    job = JobState(job_id=uuid.uuid4().hex, kind=kind)
    with _lock:
        _jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> JobState | None:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    with _lock:
        return [j.to_dict() for j in _jobs.values()]


def run_async(job: JobState, target: Callable[[JobState], Any]) -> None:
    def runner():
        job.status = "running"
        try:
            result = target(job)
            job.result = result
            job.status = "done"
        except Exception as exc:  # noqa: BLE001
            job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            job.status = "error"

    threading.Thread(target=runner, daemon=True).start()
