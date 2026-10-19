# ReelForge API

The authoritative ReelForge product backend. This directory contains the
FastAPI request tier, Celery workers, product services, persistence adapters,
and the backend-owned generation engine.

## Runtime boundary

- `app/asgi.py` assembles the public application.
- `app/router.py` owns the versioned `/api/v1` product surface.
- `app/controllers/v1/` contains incremental HTTP compatibility adapters. Root
  routing never imports them directly; each, including legacy video/LLM, is
  composed by an owning domain package until its internals are extracted.
- `app/domains/` owns product route composition. Reels owns canonical job HTTP
  workflows, B-roll owns generation and provider adapters, media owns
  caller-scoped upload registration, editor owns non-destructive export
  commands and render workflows, and the billing/publishing/identity/workspace
  domain packages establish the remaining migration boundaries.
- `app/core/auth/` and `app/core/idempotency.py` provide shared authentication
  and duplicate-command protection without coupling domains to `jobs.py`.
- `app/platform/storage/` is the canonical R2/S3 adapter. The old
  `app/services/storage/r2.py` path is an exact compatibility alias only.
- `app/core/capabilities/` owns pilot access and shared client capability
  discovery.
- `app/core/launch/` owns fail-closed public signup, checkout, and publishing
  gates; configuration of a provider alone never activates a public path.
- `app/services/` contains shared services and temporary import-compatibility
  aliases during the domain migration.
- `app/workers/` executes asynchronous reel, render, and GPU generation work.
- `engine/` is a separately packaged, typed generation capability used only by
  the CUDA generation worker. It is absent from the CPU API import path and is
  not a client API.
- `app/generation/` is a legacy/internal Pixelle compatibility application and
  is not mounted by the public ReelForge ASGI application.

Web, Expo mobile, native Rust/GPUI desktop, and both public SDKs communicate only
through `/api/v1`. They never import Python application or engine code.

## Queue ownership

| Queue | Work |
| --- | --- |
| `celery` | script, TTS, captions, notifications, and light tasks |
| `render` | avatar, composition, and editor FFmpeg exports |
| `generation` | AI B-roll and backend-owned GPU/model execution |

Postgres is the durable source of job state. Redis is the broker and
coordination layer. Private media is stored in R2 and exposed to clients through
short-lived signed URLs.

## Contract development

FastAPI OpenAPI is exported into
[`packages/api-contract`](../../packages/api-contract). Client-visible changes
must update that artifact and preserve additive `/api/v1` compatibility unless
a deprecation is explicitly approved.

```sh
npm run contract:export
npm run contract:check
npm run contract:breaking
npm run architecture:check
```

Approved generation artifacts are selected through versioned manifests under
`assets/workflows/manifests/`; client-supplied provider workflow or model names
must resolve through the server allowlist before credits are reserved.

See [`PLATFORM_ARCHITECTURE_SPEC.md`](../../docs/reelforge/PLATFORM_ARCHITECTURE_SPEC.md)
and [`REPOSITORY_LAYOUT_SPEC.md`](../../docs/reelforge/REPOSITORY_LAYOUT_SPEC.md)
for the complete ownership and migration rules.
