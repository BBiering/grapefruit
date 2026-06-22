# GCP Cloud Run Jobs setup

One-time bootstrap. After this, GitHub Actions (`.github/workflows/deploy-jobs.yml`)
builds + pushes the image and updates each job on every push to `main`.

## Prerequisites

- A GCP project with billing enabled.
- The Artifact Registry, Cloud Run, and Cloud Scheduler APIs enabled.
- A service account with these roles:
  - `Artifact Registry Writer`
  - `Cloud Run Admin`
  - `Cloud Scheduler Admin`
  - `Service Account User` (to deploy jobs that run as another SA)
  - `Service Account Token Creator` (to schedule jobs)

Export the variables we'll reuse below:

```bash
export PROJECT_ID="your-gcp-project"
export REGION="europe-west1"          # any Cloud Run region
export REPO="grapefruit"               # Artifact Registry repo name
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/grapefruit-pipelines:latest"
```

## 1. Create the Artifact Registry repo

```bash
gcloud artifacts repositories create $REPO \
  --repository-format=docker --location=$REGION \
  --description="Grapefruit Cloud Run Job images"
```

## 2. Build + push the image (first time, manually)

```bash
gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $IMAGE .
docker push $IMAGE
```

## 3. Create one Cloud Run Job per pipeline

Each job runs the same image but with a different argument. Adjust
`--cpu` / `--memory` / `--task-timeout` per job if needed. The weekly
orchestrator is the only job that needs to be long (~2h timeout).

```bash
# Secrets used by every job.
COMMON_ENV="--set-env-vars=EODHD_API_KEY=$EODHD_API_KEY,\
PERPLEXITY_API_KEY=$PERPLEXITY_API_KEY,\
DATABASE_URL=$DATABASE_URL"

for job in refresh_universe refresh_bars refresh_fundamentals \
           detect_winners enrich_catalysts refresh_watchlist \
           refresh_upcoming_events weekly; do
  gcloud run jobs create grapefruit-$job \
    --image=$IMAGE \
    --region=$REGION \
    --args=$job \
    --task-timeout=2h \
    --memory=1Gi \
    --cpu=1 \
    $COMMON_ENV
done
```

Better: store secrets in Secret Manager and use `--set-secrets=...`.

## 4. Schedule the weekly run

Cloud Scheduler hits the Cloud Run Job admin API once per week. The job
runs the `weekly` orchestrator which runs the full pipeline in order.

```bash
SA_EMAIL="scheduler-sa@$PROJECT_ID.iam.gserviceaccount.com"  # SA with Cloud Run Invoker

# Monday 09:00 UTC weekly: full pipeline
gcloud scheduler jobs create http grapefruit-weekly \
  --location=$REGION \
  --schedule="0 9 * * 1" \
  --time-zone="UTC" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/grapefruit-weekly:run" \
  --http-method=POST \
  --oauth-service-account-email=$SA_EMAIL

# 22:00 UTC daily: incremental bars refresh
gcloud scheduler jobs create http grapefruit-bars-daily \
  --location=$REGION \
  --schedule="0 22 * * *" \
  --time-zone="UTC" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/grapefruit-refresh_bars:run" \
  --http-method=POST \
  --oauth-service-account-email=$SA_EMAIL
```

## 5. Run once manually to seed the DB

```bash
gcloud run jobs execute grapefruit-refresh_universe   --region=$REGION --wait
gcloud run jobs execute grapefruit-refresh_fundamentals --region=$REGION --wait
gcloud run jobs execute grapefruit-refresh_bars       --region=$REGION --wait
gcloud run jobs execute grapefruit-detect_winners     --region=$REGION --wait
gcloud run jobs execute grapefruit-enrich_catalysts   --region=$REGION --wait
gcloud run jobs execute grapefruit-refresh_watchlist  --region=$REGION --wait
gcloud run jobs execute grapefruit-refresh_upcoming_events --region=$REGION --wait
```

The initial `refresh_bars` will take 30-60 minutes (pulling 5y daily bars for
~10k symbols). The rest finish in minutes.

## GitHub Actions secrets

Required for `.github/workflows/deploy-jobs.yml`:

- `GCP_PROJECT_ID` — the project id
- `GCP_REGION` — same as $REGION above
- `GCP_SA_KEY` — JSON key for a service account with the roles listed at the top
- `GCP_ARTIFACT_REPO` — same as $REPO above

The workflow rebuilds the image and updates every job in place. Cloud Scheduler
keeps firing; the next run uses the new image.
