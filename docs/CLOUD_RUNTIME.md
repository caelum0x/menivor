# Shared cloud runtime contract

The production infrastructure contract is standard Postgres plus
S3-compatible object storage. Neon and Cloudflare R2 are providers behind that
contract, not dependencies in domain code, and every secret remains server-side.

## Canonical environment

Copy `.env.example` to the ignored root `.env`. `DATABASE_URL` must contain a
Postgres URL, not a `psql ...` shell command. Use the pooled Neon URL for normal
application traffic. Use `DATABASE_URL_UNPOOLED` for migrations, `pg_dump`, and
`pg_restore`.

Production should use a dedicated logical database per stateful product via
`REELFORGE_DATABASE_URL`, `MINT_DATABASE_URL`, `VEND_DATABASE_URL`,
`LEDGERLINE_DATABASE_URL` and `RELAY_DATABASE_URL`.
The generic `DATABASE_URL` is a local/development fallback. Do not run every
product's independent migration history into one database.

The shared `R2_BUCKET_NAME=videogen` bucket is acceptable only for this
temporary/dev connection. Production should set `REELFORGE_R2_BUCKET_NAME` and
`RELAY_R2_BUCKET_NAME` to separate buckets and inject a distinct runtime token
scoped to each bucket. R2 token scope is bucket-level; services sharing a bucket
and token can otherwise read or delete each other's objects.

Validate configuration presence without contacting either provider or printing
values:

```bash
python3 scripts/cloud-runtime-env.py reelforge --check
python3 scripts/cloud-runtime-env.py relay --check
python3 scripts/cloud-runtime-env.py mint --check
```

Run a backend with only its required aliases injected:

```bash
PYTHONPATH=apps/api python3 scripts/cloud-runtime-env.py reelforge -- \
  .venv/bin/python -m uvicorn app.asgi:app --host 0.0.0.0 --port 8080
python3 scripts/cloud-runtime-env.py mint -- \
  cargo run --manifest-path apps/mint/Cargo.toml -p mint-server --bin mint-server
python3 scripts/cloud-runtime-env.py vend -- \
  cargo run --manifest-path apps/vend/Cargo.toml -p vend-server --bin vend-server
python3 scripts/cloud-runtime-env.py ledgerline -- \
  cargo run --manifest-path apps/ledgerline/Cargo.toml --bin ledgerline-server
python3 scripts/cloud-runtime-env.py relay -- \
  cargo run --manifest-path apps/relay/crates/Cargo.toml -p gateway -- \
    --config-file apps/relay/config/tensorzero.toml
```

Relay's active baseline is `apps/relay/config/tensorzero.toml`. The wrapper maps
R2 credentials to Relay's dedicated `S3_*` variables without overwriting
independent AWS model provider credentials.

## Product applicability

| Product | Postgres | R2 | Boundary |
| --- | --- | --- | --- |
| ReelForge API/workers | Direct | Direct | Existing SQLAlchemy/Alembic and boto3 R2 adapters |
| Mint | Direct | Not applicable | Financial ledger state is Postgres-only |
| Vend | Direct | Not applicable today | Billing/auth state is Postgres; model bytes remain in Relay |
| Ledgerline | Direct | Not applicable | Event and margin state is Postgres-only |
| Relay gateway/UI | Direct | Direct | Postgres observability/auth and S3-compatible multimodal objects |
| Prism gateway | Planned | Planned | Current Sx0 job store is process-local, with no durable adapter yet |
| Web, mobile, desktop | Never | Never | Clients call authenticated APIs; cloud secrets must not enter bundles |
| Abacus, Turnstile | Optional shared Postgres recovery/control state | `ABACUS_DATABASE_URL` / `TURNSTILE_DATABASE_URL` | Money remains in Mint; open-hold recovery and exact challenge ownership must be shared for multiple replicas |
| Agent Runtime | Not applicable | Not applicable | Persistence belongs to the embedding product |

Do not expose the R2 S3 endpoint as a public media URL. Configure an R2 custom
domain in `R2_PUBLIC_BASE_URL` for end-user assets, keep the bucket private by
default, and issue short-lived presigned URLs. Runtime credentials should have
object read/write permissions only; use a separate administrator token for
bucket creation, deletion, CORS, lifecycle, or catalog changes.

## Credential incident response

The current root `.env` has been tracked in repository history, and credentials
were also shared outside the runtime secret boundary. Adding `.env` to
`.gitignore` does not untrack an already tracked file. The repository owner
must remove it from the index in the next approved commit:

```bash
git rm --cached .env
git commit -m "stop tracking local cloud credentials"
```

Immediately rotate/revoke the Cloudflare R2 API token, R2 S3 access key and
secret, and the Neon database password/connection string. Replace local and
deployment secrets with the rotated values only after revocation. Treat history
cleanup as a separate coordinated operation; rotation is the first containment
step because rewriting Git history does not invalidate a credential.
