# Deployment

The public demo is one free Render web service built from the root `Dockerfile`, on a free Neon Postgres database. It serves the API and the Angular app on one origin, in mock AI mode, and it never compiles or runs code: the module screens show stored runs of the real local sandbox (ADR-047). It resets itself daily from a stored snapshot (ADR-048).

```text
 browser ──HTTPS──> Render (oregon, free, 512 MB)          owner's machine
                    ┌───────────────────────────────┐      ┌─────────────────────────────────┐
                    │ uvicorn: FastAPI /api/v1      │      │ docker compose stack (sandbox)  │
                    │        + Angular (same origin)│      │  alembic upgrade head            │
                    │        + job worker thread    │      │  seed: real COBOL vs real C#     │
                    │        + daily reset thread   │      │  demo_snapshot capture           │
                    └──────────────┬────────────────┘      └──────────────┬──────────────────┘
                                   │ app role (offshoot_app)              │ owner role
                                   └───────────────> Neon Postgres <──────┘
```

## What is already done

Run 05 prepared the Neon project "offshoot" (AWS us-west-2) from this machine, using the owner's direct connection in the git-ignored `.env.render`:

1. Created the login role `offshoot_app` (not a superuser, cannot create databases or roles) with a generated password.
2. Ran `alembic upgrade head` as the owner: revisions 0001 to 0005, with the app role's grants.
3. Ran the demo seed through the local sandbox and facade, then stored the demo snapshot.

`.env.render` now also holds `NEON_APP_DATABASE_URL` (the app role's connection) and four `RENDER_DEMO_PASSWORD_*` values. Those are the values Render needs. Never commit that file, and never paste its values anywhere but Render's environment screen.

## Owner steps: create the service

1. Sign in at https://dashboard.render.com with the account whose workspace has the free instance-hours.
2. Click **New** (top right), then **Blueprint**.
3. Under **Connect a repository**, pick **GitHub**, allow Render to read `ved-cmpt/offshoot` if asked (the repository can stay private), and select it.
4. Set **Branch** to `main`. Render reads `render.yaml` and lists one service, **offshoot** (web service, Docker, Free, Oregon).
5. Give the Blueprint a name, for example `offshoot`.
6. Render asks for the variables marked `sync: false`. Enter each one from `.env.render` (open it in a text editor; copy the part after the first `=`):

   | Render variable | Value comes from (in `.env.render`) | Secret |
   |---|---|---|
   | `DATABASE_URL` | `NEON_APP_DATABASE_URL` | Yes |
   | `DEMO_PASSWORD_VIEWER` | `RENDER_DEMO_PASSWORD_VIEWER` | No: published on the sign-in page |
   | `DEMO_PASSWORD_ENGINEER` | `RENDER_DEMO_PASSWORD_ENGINEER` | No: published on the sign-in page |
   | `DEMO_PASSWORD_ARCHITECT` | `RENDER_DEMO_PASSWORD_ARCHITECT` | No: published on the sign-in page |
   | `DEMO_PASSWORD_ADMIN` | `RENDER_DEMO_PASSWORD_ADMIN` | No: published on the sign-in page |

   Do not use `NEON_DATABASE_URL`: that is the owner's connection, and the service must not hold it.
7. Click **Apply** (or **Deploy Blueprint**). The first build takes several minutes: it installs the Angular toolchain, builds the app and then the Python image.
8. Open the service, wait until the status is **Live**, and copy its URL (`https://<name>.onrender.com`).
9. Check it: `https://<name>.onrender.com/healthz` answers `{"status":"ok"}`, `/api/v1/readyz` answers `{"status":"ready"}`, and the sign-in page lists the four demo accounts.

## Every environment variable on Render

All of them are in `render.yaml`. The fixed ones need no action.

| Variable | Value | Secret | Set by |
|---|---|---|---|
| `DATABASE_URL` | the app role's Neon connection | **Yes** | owner (step 6) |
| `JWT_SECRET` | random 256-bit value | **Yes** | Render (`generateValue`) |
| `DEMO_PASSWORD_VIEWER`, `_ENGINEER`, `_ARCHITECT`, `_ADMIN` | from `.env.render` | No (published) | owner (step 6) |
| `PORT` | `10000` | No | `render.yaml` |
| `APP_ENV` | `production` (refuses placeholder secrets and insecure cookies) | No | `render.yaml` |
| `DEMO_MODE` | `true` (banner, published accounts, uploads off) | No | `render.yaml` |
| `AI_MODE` | `mock` (no key on the server at all) | No | `render.yaml` |
| `EXECUTION_ENABLED` | `false` (no code is compiled or run) | No | `render.yaml` |
| `COOKIE_SECURE` | `true` (Secure cookies, HSTS) | No | `render.yaml` |
| `CORS_ORIGINS` | empty (same origin only) | No | `render.yaml` |
| `APP_DB_ROLE` | `offshoot_app` | No | `render.yaml` |
| `TRUSTED_PROXY_HOPS` | `1` (Render's proxy) | No | `render.yaml` |
| `DEMO_AUTO_RESET_HOURS` | `24` | No | `render.yaml` |
| `DEMO_DAILY_JOB_CAP` | `200` | No | `render.yaml` |
| `WRITE_RATE_LIMIT_PER_MINUTE` | `60` | No | `render.yaml` |
| `LOGIN_RATE_LIMIT_PER_MINUTE` | `10` | No | `render.yaml` |

`GEMINI_API_KEY`, `MIGRATION_DATABASE_URL`, `RUNNER_SHARED_SECRET` and `FACADE_SHARED_SECRET` are deliberately absent.

## After a change to the database schema

Render deploys every push to `main` (`autoDeployTrigger: commit`), but it does not migrate: it has no owner credentials. When a commit adds a migration, run it from this machine before or right after the deploy (PowerShell or Git Bash, from the project folder):

```bash
docker run --rm --env-file .env.render -e APP_DB_ROLE=offshoot_app \
  -v "$PWD/orchestrator:/app" -w /app offshoot-orchestrator \
  sh -c 'MIGRATION_DATABASE_URL="$NEON_DATABASE_URL" alembic upgrade head'
```

(Git Bash needs `MSYS_NO_PATHCONV=1` in front.)

## Re-seeding Neon and storing a new snapshot

The seed needs the sandbox, so it runs on this machine, with the local stack's orchestrator pointed at Neon. `docs/RUNBOOK.md` has the exact commands. Afterwards the stack goes back to its local database with `docker compose up -d orchestrator facade`.

## Cold starts and hours

A free service sleeps after 15 minutes without traffic and takes about a minute to wake. Sleeping time costs no instance-hours. The 750 free hours a month are shared with the owner's other project, which is why this is a single service.
