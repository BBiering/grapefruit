# GCP infra (managed by Pulumi)

This file used to be a long list of `gcloud` commands. The GCP resources
(Artifact Registry repo, Cloud Run Jobs, Cloud Scheduler, service accounts,
Secret Manager) are now provisioned by Pulumi.

→ See **`infra/README.md`** for the one-time bootstrap and operator cheat
sheet.

## Routine workflow recap

- Edit `backend/`, push to `main` → `.github/workflows/deploy-jobs.yml`
  builds the Docker image, pushes to Artifact Registry, and runs
  `gcloud run jobs update --image=…` for every job. Schedules keep firing.
- Edit `infra/`, push to `main` → `.github/workflows/pulumi-up.yml` runs
  `pulumi up` and applies the resource-graph change.
- Edit `frontend/`, push to `main` → Vercel rebuilds the SPA.

## Seeding the database (first run only)

After `pulumi up` completes, kick the pipelines in order to populate
Supabase:

```bash
for job in refresh_universe refresh_fundamentals refresh_bars \
           detect_winners enrich_catalysts refresh_watchlist \
           refresh_upcoming_events; do
  gcloud run jobs execute "grapefruit-${job}" --region="$REGION" --wait
done
```

`refresh_bars` is the long one (30–60 minutes for ~10k symbols, 5y of daily
bars). Everything else finishes in minutes.
