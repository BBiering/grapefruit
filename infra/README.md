# Pulumi: GCP infra for Grapefruit pipelines

Pulumi owns the **structure** of the GCP resources (Artifact Registry repo,
two service accounts + IAM, three Secret Manager secrets, eight Cloud Run
Jobs, two Cloud Scheduler entries). The image bytes are rolled out separately
by `.github/workflows/deploy-jobs.yml` (it calls `gcloud run jobs update
--image=...` on each push to `main`), so routine pipeline code changes never
touch Pulumi.

## One-time operator bootstrap

You never touch your laptop for config: the `pulumi-up.yml` workflow injects
every config value from GitHub repo secrets at runtime (the "Set config from
GitHub secrets" step). The committed `Pulumi.prod.yaml` is intentionally
config-free — don't commit project IDs or secrets into it.

The only bootstrap that can't run in CI is creating the state bucket and
enabling APIs. Do this once from Cloud Shell (still no laptop) or any machine
with `gcloud`:

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
```

After that, set the GitHub secrets below and trigger the **Pulumi up** workflow
(`workflow_dispatch` → `up`, or push to `infra/**`). Every push to `main` that
touches `infra/**` re-runs `pulumi up` non-interactively via
`.github/workflows/pulumi-up.yml`. The image gets rebuilt and rolled by
`.github/workflows/deploy-jobs.yml` on the same push if backend code changed.

## GitHub Actions secrets

`pulumi-up.yml` reads all of its config from these. In addition to the four GCP
secrets already used by `deploy-jobs.yml`
(`GCP_SA_KEY`, `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_ARTIFACT_REPO`), add:

- `PULUMI_STATE_BUCKET` — e.g. `grapefruit-pulumi-state` (no `gs://` prefix).
- `PULUMI_CONFIG_PASSPHRASE` — a long random string; encrypts the secret config
  at rest in the GCS state. Choose once, never changes.
- `EODHD_API_KEY`
- `PERPLEXITY_API_KEY`
- `DATABASE_URL` — the `postgres://...` connection string.

`image_uri` is derived in the workflow from `GCP_REGION`, `GCP_PROJECT_ID`, and
`GCP_ARTIFACT_REPO`, so it needs no dedicated secret.

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
