FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# Install deps separately so pyproject changes invalidate the cache layer only.
# README.md is needed because pyproject declares `readme = "README.md"` and
# uv builds the local grapefruit package during sync.
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

COPY backend ./backend

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

# Cloud Run Job entrypoint: `python -m grapefruit.pipelines <job_name>`.
# The job_name is appended as a CMD via the Cloud Run Job spec or env.
ENTRYPOINT ["uv", "run", "python", "-m", "grapefruit.pipelines"]
