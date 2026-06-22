# Pulumi: GCP infra for Grapefruit pipelines

Pulumi owns the **structure** of the GCP resources (Artifact Registry repo,
two service accounts + IAM, three Secret Manager secrets, eight Cloud Run
Jobs, two Cloud Scheduler entries). The image bytes are rolled out separately
by `.github/workflows/deploy-jobs.yml` (it calls `gcloud run jobs update
--image=...` on each push to `main`), so routine pipeline code changes never
touch Pulumi.

## One-time operator bootstrap

```bash
export PROJECT_ID="your-gcp-project"
export REGION="europe-west1"

# Enable APIs.
gcloud config set project "$PROJECT_ID"
gcloud services enable \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com

# State bucket (one-time; keep it OUT of any Pulumi-managed project).
gsutil mb -l "$REGION" "gs://grapefruit-pulumi-state"
gsutil versioning set on "gs://grapefruit-pulumi-state"

# Local auth.
gcloud auth application-default login

# Pulumi state + stack.
cd infra
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export PULUMI_CONFIG_PASSPHRASE="<choose a long random string and save it>"
pulumi login "gs://grapefruit-pulumi-state"
pulumi stack init prod

# Config (plain).
pulumi config set gcp:project "$PROJECT_ID"
pulumi config set gcp:region  "$REGION"
pulumi config set image_uri   "$REGION-docker.pkg.dev/$PROJECT_ID/grapefruit-pipelines/grapefruit-pipelines:latest"

# Config (secrets).
pulumi config set --secret eodhd_api_key      "$EODHD_API_KEY"
pulumi config set --secret perplexity_api_key "$PERPLEXITY_API_KEY"
pulumi config set --secret database_url       "$DATABASE_URL"

# First run.
pulumi up --yes
```

After this, every push to `main` that touches `infra/**` re-runs `pulumi up`
non-interactively via `.github/workflows/pulumi-up.yml`. The image gets
rebuilt and rolled by `.github/workflows/deploy-jobs.yml` on the same push if
backend code changed.

## GitHub Actions secrets

In addition to the four GCP secrets already used by `deploy-jobs.yml`
(`GCP_SA_KEY`, `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ARTIFACT_REPO`), add:

- `PULUMI_STATE_BUCKET` — e.g. `grapefruit-pulumi-state` (no `gs://` prefix).
- `PULUMI_CONFIG_PASSPHRASE` — the same passphrase you exported locally above.

The `GCP_SA_KEY` service account needs these roles (grant once in the GCP
console or via `gcloud projects add-iam-policy-binding`):

- `roles/artifactregistry.admin`
- `roles/run.admin`
- `roles/cloudscheduler.admin`
- `roles/iam.serviceAccountAdmin`
- `roles/secretmanager.admin`
- `roles/iam.serviceAccountUser` (so Pulumi can attach SAs to the jobs)

## Cheat sheet

```bash
pulumi preview     # dry-run diff
pulumi up          # apply (CI does this with --yes)
pulumi stack output    # print exported values
pulumi config set --secret database_url "<new value>"   # rotate a secret
pulumi destroy     # tear it all down (don't run this in CI)
```
