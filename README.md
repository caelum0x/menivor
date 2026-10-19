# Menivor

**[menivor.com](https://menivor.com)** — turn a screen recording into a polished,
captioned UGC/avatar video: AI script generation, ElevenLabs voice, karaoke-style
word-by-word captions, and an optional lip-synced AI presenter, composed into a
1080×1920 MP4 ready to post.

This repository is the **open-source core** of Menivor: the generation
pipeline, the product backend, and the web, mobile, and native desktop clients
that run on top of it. It is a real, running product's source, not a
stripped-down demo.

```
screen_recording.mp4 + prompt + language + avatar + voice
  → SCRIPT      (LLM, structured JSON hooks)
  → TTS         (ElevenLabs /with-timestamps — the single timing authority)
  → AVATAR      (HeyGen, or self-hosted lip-sync, optional)
  → CAPTIONS    (ASS karaoke, burned via libass)
  → COMPOSE     (pure FFmpeg: chroma PiP + layouts, hw-accel where available)
  → 1080×1920 MP4 (+ optional direct publish to TikTok/IG/YouTube Shorts)
```

## What's in this repo

| Path | What it is |
|---|---|
| [`apps/api`](apps/api) | The FastAPI product backend: the generation pipeline (script → TTS → captions → compose), job/queue orchestration (Celery + Redis), persistence, and the public `/api/v1` contract every client talks to. |
| [`apps/web`](apps/web) | The Next.js 15 web app — creator workspace, editor, and marketing site. |
| [`apps/mobile`](apps/mobile) | The Expo (React Native) mobile app — capture, generate, and manage reels from a phone. |
| [`apps/desktop`](apps/desktop) | The native Rust/GPUI desktop client — a generation workspace with its own OS-level credential storage. |
| [`packages/*`](packages) | Shared contracts and libraries used by more than one app: the OpenAPI contract, caption engine, FFmpeg compose core, provider-adapter kit, publishing connectors, TypeScript/Python SDKs, UI kit, and schema packages. |
| [`external/REGISTRY.md`](external/REGISTRY.md) | A governance record of every third-party/open-source project evaluated for the generation pipeline (ComfyUI, Wan2.2, OpenCut, etc.), with license and adoption-state notes. |
| [`docs/adr`](docs/adr) | Architecture decision records explaining why the system is shaped the way it is. |

Note: `external/REGISTRY.md` is included for attribution/governance; the
research checkouts it inventories (ComfyUI, Wan2.2, etc.) are not vendored
into this repo.

Every app and package here is real, runnable product source — this is what
ships in the live product, not a rewritten subset.

## What's *not* in this repo (the hosted layer)

Menivor the open-source project and **menivor.com** the hosted product share
this codebase, but the hosted product adds a paid infrastructure layer that is
intentionally kept out of this public repo:

- **Metered media rendering gateway** — the production routing/failover/BYOK
  gateway in front of 10+ paid image, video, and audio model providers, with
  exact-cost metering and spend caps.
- **Wallet/settlement ledger** — the double-entry billing ledger that meters
  and settles paid generation and publishing usage.
- **Hosted distribution surfaces** — the TV/viewer app, live-streaming, and
  casting infrastructure that ship finished videos to channels.
- **Production deploy config** — the Cloudflare/Kubernetes/Terraform config,
  CI/CD deploy pipeline, and any file that referenced our live account IDs,
  internal hostnames, or production credentials. (Every config file in this
  repo is a template — copy the `.example` file and fill in your own values.)

You can self-host the full generation pipeline and all four client apps with
your own API keys for the model providers you want (Anthropic/OpenAI for
script generation, ElevenLabs for voice, HeyGen for avatars, Replicate/fal/
Higgsfield for AI video, Stripe/Creem/Iyzico/Polar for billing — all
optional and independently gated). What you don't get out of the box is our
specific hosted infrastructure for routing and metering those providers at
scale — that part stays at [menivor.com](https://menivor.com).

## Quickstart (self-hosted API)

```bash
cd apps/api
cp .env.example .env
$EDITOR .env          # at minimum, set REELFORGE_DEVICE_AUTH_SECRET
                       # (openssl rand -hex 32); provider/billing keys are
                       # optional — every feature fails closed without them
docker compose up --build
```

This brings up Postgres, Redis, MinIO (a local S3-compatible stand-in for
Cloudflare R2), runs database migrations, and serves `/api/v1` on
`127.0.0.1:8080`. See [`apps/api/README.md`](apps/api/README.md) for the full
runtime architecture.

Then run a client against it:

```bash
# Web
cd apps/web && npm install && cp .env.example .env.local && npm run dev

# Mobile (Expo)
cd apps/mobile && npm install && cp .env.example .env.local && npx expo start

# Desktop (Rust/GPUI)
cd apps/desktop && cargo run
```

Every provider integration (LLM, TTS, avatar, AI video, billing, social
publishing) is optional and gated: the API boots and serves core functionality
with zero provider keys configured, and each feature activates only once its
specific key is set. See each app's own README for its environment variables
and full setup.

## Built on MoneyPrinterTurbo

Menivor is built on top of
[**MoneyPrinterTurbo**](https://github.com/harry0703/MoneyPrinterTurbo) (MIT
licensed) — the FastAPI service shape, the script → TTS → subtitle → compose
pipeline, and much of `apps/api/app/services/*` descend from it, extended into
a production SaaS backend plus web, mobile, and desktop clients. The original
MoneyPrinterTurbo README is preserved as
[`README-mpt.md`](./README-mpt.md). The non-destructive timeline editor in
`apps/web` is similarly built on [**OpenCut**](https://github.com/OpenCut-app/OpenCut)
(MIT). Full attribution, including every other third-party project consulted
or ported, is in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md),
[`NOTICE`](NOTICE), and [`external/REGISTRY.md`](external/REGISTRY.md).

## License

MIT — see [`LICENSE`](LICENSE). This covers Menivor's own code. Third-party
code retains its own license as documented in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and
[`external/REGISTRY.md`](external/REGISTRY.md); nothing under `external/` is
redistributed as product source.

## Links

- Hosted product: **[menivor.com](https://menivor.com)**
- Issues and feature requests: use this repo's [issue tracker](../../issues)
