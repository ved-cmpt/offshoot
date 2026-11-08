# Runbook

Operating the public demo and the local stack. Deployment itself is in [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Health

| Check | Healthy |
|---|---|
| `GET /healthz` | `{"status":"ok"}`; no database access, used by Render's health check |
| `GET /api/v1/readyz` | `{"status":"ready"}`; 503 `database_unavailable` or `not_migrated` otherwise |
| `GET /api/v1/config` | `demo_mode: true`, `ai_mode: "mock"`, `execution_enabled: false`, `demo_reset_hours: 24` on the public demo |

The first request after 15 idle minutes wakes the service, which takes about a minute. Neon's free compute also suspends when idle and resumes on the first query.

## The daily reset

The service restores the stored demo snapshot once it is 24 hours old, checking at start and every 5 minutes (ADR-048). Each reset writes a `demo.reset` entry with `mode: snapshot` to the audit log, which architects and admins can read in the app.

To see the snapshot's state from this machine:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --env-file .env.render \
  -v "$PWD/orchestrator:/app" -w /app offshoot-orchestrator \
  sh -c 'DATABASE_URL="$NEON_APP_DATABASE_URL" JWT_SECRET=status-only-not-a-real-secret-0123456789 python -m app.scripts.demo_snapshot status'
```

To reset at once, replace `status` with `restore` (it needs `DEMO_MODE=true`, the default).

## Re-seeding Neon (needs the local sandbox)

Only after a change to BillRite, the fixtures or the seed. It replaces the demo project and stores a new snapshot. From the project folder, in Git Bash:

```bash
# 1. A Compose override that points the local orchestrator at Neon, in a scratch folder.
cat > /tmp/neon.override.yaml <<'YAML'
services:
  orchestrator:
    environment:
      DATABASE_URL: ${NEON_APP_DATABASE_URL:?}
      MIGRATION_DATABASE_URL: ${NEON_DATABASE_URL:?}
      # Only the seed runs jobs, so two mutation runs never share the builder.
      JOB_WORKER_ENABLED: "false"
YAML
# 2. Recreate the orchestrator and the facade with it.
docker compose --env-file .env --env-file .env.render -f compose.yaml -f /tmp/neon.override.yaml up -d orchestrator facade
# 3. Seed, then store the snapshot the daily reset restores.
# Never capture after a failed seed: a snapshot of a broken state would be restored daily.
docker compose exec -T orchestrator python -m app.scripts.reset_demo --confirm \
  && docker compose exec -T orchestrator python -m app.scripts.demo_snapshot capture
# 4. Back to the local database.
docker compose up -d orchestrator facade
rm /tmp/neon.override.yaml
```

Never run `docker compose config` with the override in place: it prints the connection strings.

## Limits and what to watch

| What | Limit | Where to look |
|---|---|---|
| Render instance-hours | 750 a month for the whole workspace, shared with another project | Render dashboard, Billing |
| Neon storage | 0.5 GB on the free plan; the append-only audit log grows by a few rows per visitor action | Neon console, project "offshoot" |
| Jobs on the demo | 200 in any 24 hours (`DEMO_DAILY_JOB_CAP`), then 429 `DEMO_CAP_REACHED` until older jobs age out or the reset removes them | Audit log, `GET /api/v1/projects/{id}/jobs` |
| Writes per visitor | 60 mutating requests a minute per address, then 429 `RATE_LIMITED` | Response headers (`Retry-After`) |
| Sign-ins | 10 a minute per address and account, 60 per address | ADR-015 |
| Memory | 512 MB; about 92 MB when idle in the local production container | Render metrics |

## Incidents

| Symptom | Likely cause | Action |
|---|---|---|
| `readyz` says `not_migrated` | A deploy brought a migration that was not run | Run the migration command in `DEPLOYMENT.md` |
| Sign-in fails for every demo account | The accounts were changed in the database by hand (the API refuses it in demo mode, ADR-050) | Restart the service in Render; at start it restores `viewer`, `engineer`, `architect` and `admin` with `demo1234` |
| Every module screen is empty | The snapshot was never stored, or the project was deleted | Re-seed (above) |
| A visitor filled the job cap | Expected under load | Nothing; it frees itself, or restore the snapshot |
| Neon storage close to the limit | Audit growth over months | Export what is needed and start a fresh Neon branch; the audit log cannot be trimmed by the app role, by design (ADR-014) |

## Local stack

See the README. `docker compose exec orchestrator python -m app.scripts.reset_demo --confirm` re-seeds the local demo through the real sandbox; with `--snapshot` it restores the last captured snapshot instead. The production image runs locally with `docker compose -f compose.prod.yaml up --build -d` on http://localhost:8300.
