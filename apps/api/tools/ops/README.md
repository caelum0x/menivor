# ReelForge — Run Harness (`ops/`)

Bring the **whole** ReelForge product up locally and smoke-test it with one
command. Everything here is **new, additive, and non-destructive**: it drives the
existing app code (FastAPI + Celery + Next.js) read-only and does not modify any
application source, the existing `docker-compose.reelforge.yml`, the `Dockerfile`,
or `Makefile.reelforge`.

## KEEP — do not delete or fold into other files

> These files are the operator entrypoint for the full stack. Keep them as
> **separate, new files** so the fork stays non-destructive:
>
> - `docker-compose.full.yml` — the complete local stack (postgres + redis + api
>   + worker + beat + web). Distinct from `docker-compose.reelforge.yml`, which is
>   Neon-backed and ships no database or web service.
> - `.env.full.example` — env template for the full stack (local Postgres wired in).
> - `Makefile.dev` — `up` / `down` / `logs` / `gate` / `smoke` / `seed` / `fmt`.
> - `ops/web.Dockerfile` (+ `ops/web.Dockerfile.dockerignore`) — the Next.js image.
> - `ops/smoke.py`, `ops/seed.py`, `scripts/dev-bootstrap.sh`.

## What comes up

`docker-compose.full.yml` builds/starts, all on `127.0.0.1`:

| Service    | Image / build                | Port  | Role |
|------------|------------------------------|-------|------|
| `postgres` | `postgres:16-alpine`         | 5432  | Local Postgres (stands in for Neon) |
| `redis`    | `redis:7-alpine`             | 6379  | Celery broker/result backend + task store |
| `migrate`  | repo `Dockerfile` (one-shot) | —     | `alembic upgrade head`, then exits |
| `api`      | repo `Dockerfile`            | 8080  | FastAPI `app.asgi:app` (`/api/v1`, `/docs`, `/openapi.json`) |
| `worker`   | repo `Dockerfile`            | —     | Celery worker (`celery,render` queues) |
| `beat`     | repo `Dockerfile`            | —     | Celery beat (scheduled-publish due-runner, 1/min) |
| `web`      | `ops/web.Dockerfile`         | 3000  | Next.js frontend (`next start`) |

Startup ordering is enforced with healthchecks + `depends_on`: `postgres`/`redis`
become healthy → `migrate` runs to completion → `api`/`worker`/`beat` start →
`web` starts once `api` is healthy.

## Quick start

```bash
# 1. Configure env (placeholders are enough to boot; add real keys for live calls)
cp .env.full.example .env.full

# 2. Bring the whole stack up
make -f Makefile.dev up

# 3. Smoke-test it end-to-end
make -f Makefile.dev smoke

# 4. (optional) Seed demo data, then browse
make -f Makefile.dev seed
open http://localhost:3000        # web
open http://localhost:8080/docs   # API docs

# Tear down
make -f Makefile.dev down
```

Without Docker (backend only): `./scripts/dev-bootstrap.sh` creates a venv,
installs deps, copies the env file, and runs migrations. Then run the API and a
worker with the `Makefile.reelforge` `api` / `worker` targets.

## The quality gate

`make -f Makefile.dev gate` runs the same checks CI does, in order:

1. `ruff check --select F,E9` — fatal lint only (pyflakes + syntax errors).
2. `pytest tests/reelforge` — the ReelForge suite.
3. `alembic upgrade head` — the schema applies cleanly.
4. `alembic check` — no un-migrated drift between models and migrations.

The alembic steps need `NEON_DATABASE_URL` (the full stack sets it in `.env.full`;
export it, or point it at a throwaway database). Uses `uv run` when `uv` is
installed, otherwise the bare tools on `PATH`.

## The smoke test (`ops/smoke.py`)

Standard-library only (no project deps required). Independent checks, one summary:

- **redis** — raw TCP `PING` → `+PONG`.
- **api.openapi** — `GET /openapi.json` is 200 and advertises `/api/v1` paths.
- **api.ping** / **api.docs** — best-effort `/ping` and Swagger UI probes.
- **web** — `GET /` returns < 500.
- **celery** — optional `inspect ping` when `celery` + app config import.

Required checks must pass for exit 0; optional checks are reported but don't fail
the run unless `SMOKE_STRICT=1`. Override targets via `SMOKE_API_URL`,
`SMOKE_WEB_URL`, `SMOKE_REDIS_HOST`, `SMOKE_REDIS_PORT`.

## The seeder (`ops/seed.py`)

Inserts an **idempotent** demo dataset (one demo user keyed by
`SEED_USER_EMAIL`, plus one demo avatar-reel job) using the existing session
factory and `JobRepository`. Re-running never duplicates rows. Requires the
schema to exist (`migrate` service / `make -f Makefile.dev migrate`).

## Validating the compose file

```bash
# With Docker + the compose plugin:
docker compose -f docker-compose.full.yml config -q

# Without Docker (YAML parse only):
python -c "import yaml; yaml.safe_load(open('docker-compose.full.yml'))"
```

## Notes & caveats

- **Placeholders boot; real keys run the pipeline.** `.env.full.example` ships
  non-empty placeholders for the R2/`NEON_DATABASE_URL` values the worker
  entrypoint requires, so the stack starts. Live script/TTS/avatar/upload calls
  need real `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `HEYGEN_API_KEY`, and R2
  credentials.
- **Web auth.** The frontend uses Clerk. The image builds with placeholder
  `NEXT_PUBLIC_*` values; provide real `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` +
  `CLERK_SECRET_KEY` for a working sign-in flow.
- **Local Postgres, not Neon.** This stack points `NEON_DATABASE_URL` at the
  bundled `postgres` service so it is fully self-contained. To use real Neon,
  set `NEON_DATABASE_URL` to your Neon URL and you can ignore the `postgres`
  service.
