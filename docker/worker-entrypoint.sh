#!/usr/bin/env bash
#
# ReelForge Celery worker entrypoint.
#
# Responsibilities before handing off to the Celery worker command:
#   1. Fail fast if the core-infra secrets are missing (contract §3.4: R2 + Neon
#      are required at worker startup; per-feature keys are validated per-job).
#   2. Wait for Redis (broker/backend) to accept connections so the worker does
#      not crash-loop on a cold `docker compose up`.
#   3. exec the passed command (the `celery ... worker` line from compose) as PID 1
#      so signals (SIGTERM on shutdown) are delivered to the worker cleanly.
#
# It intentionally does NOT run DB migrations — that is an explicit, one-shot
# operation (`make -f Makefile.reelforge migrate`) so concurrent workers never
# race on `alembic upgrade head`.

set -euo pipefail

log() { printf '[worker-entrypoint] %s\n' "$*"; }

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

# --- 1. Core-infra secret validation (fail fast, no mid-pipeline crashes) ---
# Adapt the monorepo's canonical names inside this process. Values are never
# logged, and explicit ReelForge-specific variables keep precedence.
export NEON_DATABASE_URL="${REELFORGE_DATABASE_URL:-${NEON_DATABASE_URL:-${DATABASE_URL:-}}}"
export R2_BUCKET="${REELFORGE_R2_BUCKET_NAME:-${R2_BUCKET_NAME:-${R2_BUCKET:-}}}"

missing=()
[ -n "${NEON_DATABASE_URL:-}" ] || missing+=("NEON_DATABASE_URL")
[ -n "${R2_ACCOUNT_ID:-}" ]     || missing+=("R2_ACCOUNT_ID")
[ -n "${R2_ACCESS_KEY_ID:-}" ]  || missing+=("R2_ACCESS_KEY_ID")
[ -n "${R2_SECRET_ACCESS_KEY:-}" ] || missing+=("R2_SECRET_ACCESS_KEY")
[ -n "${R2_BUCKET:-}" ]         || missing+=("R2_BUCKET")

if [ "${#missing[@]}" -gt 0 ]; then
  log "FATAL: missing required core-infra env vars: ${missing[*]}"
  log "Populate them in .env.reelforge (see .env.reelforge.example) and retry."
  exit 1
fi

# --- 2. Wait for Redis to be reachable ---
log "Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT} ..."
attempts=0
max_attempts=30
until python3 - "$REDIS_HOST" "$REDIS_PORT" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
do
  attempts=$((attempts + 1))
  if [ "$attempts" -ge "$max_attempts" ]; then
    log "FATAL: Redis not reachable after ${max_attempts} attempts."
    exit 1
  fi
  sleep 2
done
log "Redis is up."

# --- 3. Hand off to the Celery worker command (PID 1 signal handling) ---
log "Starting: $*"
exec "$@"
