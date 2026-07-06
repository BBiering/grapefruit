"""Pulumi program for Grapefruit's GCP infra.

Resources (one stack: prod):

- Artifact Registry repo for the pipelines Docker image.
- Two service accounts: `runner` (Cloud Run Job identity) and `scheduler`
  (Cloud Scheduler identity, with run.invoker on each job).
- Three Secret Manager secrets (EODHD_API_KEY, PERPLEXITY_API_KEY,
  DATABASE_URL) populated from Pulumi config; runner SA reads them.
- One Cloud Run v2 Job per pipeline (see `JOB_NAMES`), all built from the
  same image with the job name passed as `args`. The `weekly` orchestrator
  gets a 2h timeout; everything else 30m.
- Two Cloud Scheduler HTTP jobs that POST to the Cloud Run Jobs' `:run`
  endpoint via the scheduler SA.

Routine pipeline code changes are NOT applied by Pulumi — the
`deploy-jobs.yml` workflow builds a new image and runs
`gcloud run jobs update --image=...` for each job, leaving the rest of the
job spec (env, args, timeout, schedule) under Pulumi's ownership.
"""
from __future__ import annotations

import pulumi
import pulumi_gcp as gcp


# ---------------------------------------------------------------------------
# Stack config
# ---------------------------------------------------------------------------

config = pulumi.Config()
gcp_config = pulumi.Config("gcp")

PROJECT_ID: str = gcp_config.require("project")
REGION: str = gcp_config.require("region")
IMAGE_URI: str = config.require("image_uri")  # e.g. <region>-docker.pkg.dev/<proj>/<repo>/grapefruit-pipelines:latest

EODHD_API_KEY = config.require_secret("eodhd_api_key")
PERPLEXITY_API_KEY = config.require_secret("perplexity_api_key")
DATABASE_URL = config.require_secret("database_url")


# ---------------------------------------------------------------------------
# Pipeline catalog
# ---------------------------------------------------------------------------

JOB_NAMES = [
    "refresh_universe",
    "refresh_bars",
    "refresh_fundamentals",
    "detect_winners",
    "detect_watchlist_moves",
    "enrich_catalysts",
    "refresh_watchlist",
    "refresh_sectors",
    "refresh_upcoming_events",
    "scan_forward_catalysts",
    "compute_strategy_tags",
    "weekly",
]

# Per-job overrides: weekly is the long orchestrator.
TIMEOUTS = {"weekly": "7200s"}   # 2h
DEFAULT_TIMEOUT = "1800s"        # 30m
DEFAULT_MEMORY = "1Gi"
DEFAULT_CPU = "1"


# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------

repo = gcp.artifactregistry.Repository(
    "pipelines-repo",
    repository_id="grapefruit-pipelines",
    location=REGION,
    format="DOCKER",
    description="Grapefruit pipeline images",
)


# ---------------------------------------------------------------------------
# Service accounts
# ---------------------------------------------------------------------------

runner_sa = gcp.serviceaccount.Account(
    "runner-sa",
    account_id="grapefruit-runner",
    display_name="Cloud Run Job identity for Grapefruit pipelines",
)

scheduler_sa = gcp.serviceaccount.Account(
    "scheduler-sa",
    account_id="grapefruit-scheduler",
    display_name="Cloud Scheduler identity that invokes Grapefruit Cloud Run Jobs",
)


# ---------------------------------------------------------------------------
# Secret Manager
# ---------------------------------------------------------------------------

def _secret(name: str, value: pulumi.Output[str]) -> gcp.secretmanager.Secret:
    secret = gcp.secretmanager.Secret(
        f"{name}-secret",
        secret_id=name,
        replication=gcp.secretmanager.SecretReplicationArgs(auto={}),
    )
    gcp.secretmanager.SecretVersion(
        f"{name}-secret-version",
        secret=secret.id,
        secret_data=value,
    )
    gcp.secretmanager.SecretIamMember(
        f"{name}-runner-access",
        secret_id=secret.id,
        role="roles/secretmanager.secretAccessor",
        member=runner_sa.email.apply(lambda e: f"serviceAccount:{e}"),
    )
    return secret


eodhd_secret = _secret("EODHD_API_KEY", EODHD_API_KEY)
perplexity_secret = _secret("PERPLEXITY_API_KEY", PERPLEXITY_API_KEY)
database_url_secret = _secret("DATABASE_URL", DATABASE_URL)


# ---------------------------------------------------------------------------
# Cloud Run Jobs
# ---------------------------------------------------------------------------

def _env_from_secret(name: str, secret: gcp.secretmanager.Secret) -> gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs:
    return gcp.cloudrunv2.JobTemplateTemplateContainerEnvArgs(
        name=name,
        value_source=gcp.cloudrunv2.JobTemplateTemplateContainerEnvValueSourceArgs(
            secret_key_ref=gcp.cloudrunv2.JobTemplateTemplateContainerEnvValueSourceSecretKeyRefArgs(
                secret=secret.secret_id,
                version="latest",
            ),
        ),
    )


def _make_job(job_name: str) -> gcp.cloudrunv2.Job:
    # Cloud Run job_id allows only lowercase letters, digits, and hyphens, so
    # the resource name is hyphenated. The container arg keeps the underscore
    # form because it maps to a Python module / KNOWN_JOBS key in
    # grapefruit.pipelines.__main__.
    return gcp.cloudrunv2.Job(
        f"job-{job_name}",
        name=f"grapefruit-{job_name.replace('_', '-')}",
        location=REGION,
        template=gcp.cloudrunv2.JobTemplateArgs(
            template=gcp.cloudrunv2.JobTemplateTemplateArgs(
                service_account=runner_sa.email,
                timeout=TIMEOUTS.get(job_name, DEFAULT_TIMEOUT),
                max_retries=1,
                containers=[
                    gcp.cloudrunv2.JobTemplateTemplateContainerArgs(
                        image=IMAGE_URI,
                        args=[job_name],
                        resources=gcp.cloudrunv2.JobTemplateTemplateContainerResourcesArgs(
                            limits={"memory": DEFAULT_MEMORY, "cpu": DEFAULT_CPU},
                        ),
                        envs=[
                            _env_from_secret("EODHD_API_KEY", eodhd_secret),
                            _env_from_secret("PERPLEXITY_API_KEY", perplexity_secret),
                            _env_from_secret("DATABASE_URL", database_url_secret),
                        ],
                    ),
                ],
            ),
        ),
        # The image is rotated by the deploy-jobs.yml workflow via
        # `gcloud run jobs update --image=...`. Pulumi shouldn't fight it.
        opts=pulumi.ResourceOptions(ignore_changes=["template.template.containers[0].image"]),
    )


jobs: dict[str, gcp.cloudrunv2.Job] = {name: _make_job(name) for name in JOB_NAMES}


# Allow the scheduler SA to invoke each job.
for name, job in jobs.items():
    gcp.cloudrunv2.JobIamMember(
        f"job-{name}-invoker",
        location=REGION,
        name=job.name,
        role="roles/run.invoker",
        member=scheduler_sa.email.apply(lambda e: f"serviceAccount:{e}"),
    )


# ---------------------------------------------------------------------------
# Cloud Scheduler
# ---------------------------------------------------------------------------

def _scheduler(scheduler_name: str, job_name: str, cron: str, description: str) -> gcp.cloudscheduler.Job:
    job = jobs[job_name]
    uri = pulumi.Output.all(REGION, PROJECT_ID, job.name).apply(
        lambda parts: f"https://{parts[0]}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/{parts[1]}/jobs/{parts[2]}:run"
    )
    return gcp.cloudscheduler.Job(
        f"sched-{scheduler_name}",
        name=f"grapefruit-{scheduler_name}",
        region=REGION,
        schedule=cron,
        time_zone="UTC",
        description=description,
        http_target=gcp.cloudscheduler.JobHttpTargetArgs(
            uri=uri,
            http_method="POST",
            oauth_token=gcp.cloudscheduler.JobHttpTargetOauthTokenArgs(
                service_account_email=scheduler_sa.email,
            ),
        ),
    )


weekly_schedule = _scheduler(
    "weekly", "weekly", "0 9 * * 1", "Monday 09:00 UTC: full pipeline"
)
bars_daily_schedule = _scheduler(
    "bars-daily", "refresh_bars", "0 22 * * *", "Daily 22:00 UTC: incremental bars"
)


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

pulumi.export("image_repository_url", repo.repository_id.apply(
    lambda rid: f"{REGION}-docker.pkg.dev/{PROJECT_ID}/{rid}"
))
pulumi.export("runner_sa_email", runner_sa.email)
pulumi.export("scheduler_sa_email", scheduler_sa.email)
pulumi.export("job_names", [j.name for j in jobs.values()])
