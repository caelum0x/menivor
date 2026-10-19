# ReelForge Web

The Next.js 15 frontend for **ReelForge** — turn a screen recording into a
polished UGC avatar reel (AI script, ElevenLabs voice, karaoke captions, and a
HeyGen talking-head presenter).

## Stack

- **Next.js 15** (App Router) + **React 19** + **TypeScript** (strict)
- **Tailwind CSS 3** + a small **shadcn-style** UI kit (`components/ui/`)
- **Clerk** for auth (email + Google)
- **Cloudflare Workers** deploy target via [`@opennextjs/cloudflare`](https://opennext.js.org/cloudflare)

## Getting started

```bash
npm install
cp .env.example .env.local   # fill in Clerk keys + API base
npm run dev                  # http://localhost:3000
```

### Scripts

| Script          | Purpose                     |
| --------------- | --------------------------- |
| `npm run dev`   | Start the dev server        |
| `npm run build` | Production build            |
| `npm run start` | Serve the production build  |
| `npm run lint`  | ESLint (`next lint`)        |
| `npm run cf:build`   | Build the Cloudflare Worker bundle (`.open-next/`) |
| `npm run cf:preview` | Build + run the Worker locally in workerd          |
| `npm run cf:deploy`  | Build + deploy the Worker (needs CF account creds) |

## Environment

See [`.env.example`](./.env.example). All client-visible config uses
`NEXT_PUBLIC_*`; **never** put real secrets in a `NEXT_PUBLIC_*` var.

| Var                                 | Purpose                                                             |
| ----------------------------------- | ------------------------------------------------------------------ |
| `NEXT_PUBLIC_API_BASE`              | Backend v1 base URL (default `http://localhost:8080/api/v1`)        |
| `NEXT_PUBLIC_APP_API_KEY`           | Public `x-api-key` fallback when no Clerk JWT is sent               |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key (browser-safe)                               |
| `CLERK_SECRET_KEY`                  | Clerk secret key (server-only)                                     |

## Architecture and ownership

```text
app/                 Next.js routes and server/client composition
src/features/        Product feature controllers and their public exports
components/<feature> Transitional/presentational feature components
src/shared/api/      Authenticated browser transport over `/api/v1`
src/features/editor  Active non-destructive reel editor workspace
lib/api.ts           Feature methods + compatibility exports over shared transport
lib/types.ts         Transitional feature exports over the shared contract
editor-module/       Read-only OpenCut migration source
editor-bff/          Optional stateless editor transport Worker
middleware.ts        Clerk route protection
```

`reel-create`, `broll-studio`, and `jobs-library` own the active workflow
controllers. App Router files import those public feature boundaries and remain
limited to metadata and page composition.

Public reel, B-roll, upload, job-state, error, and capability semantics come
from `@reelforge/api-contract`. FastAPI remains authoritative for identity,
credits, jobs, media ownership, provider selection, and signed previews. The
editor BFF cannot own durable product state.

`/dashboard` and `/new` are auth-protected by [`middleware.ts`](./middleware.ts).

## API client (`src/shared/api` + `lib/api.ts`)

A shared transport plus typed feature methods for every backend v1 endpoint (§5 of
`docs/reelforge/INTEGRATION_CONTRACT.md`). Every request sends an `x-api-key`
header — a per-call token (e.g. a Clerk JWT) if provided, otherwise
`NEXT_PUBLIC_APP_API_KEY`. Responses are unwrapped from the backend
`{ status, data, message }` envelope; non-2xx responses throw `ApiError`.

```ts
import { useAuth } from "@clerk/nextjs";
import * as api from "@/lib/api";
import type { ReelForgeParams } from "@/lib/types";

const { getToken } = useAuth();
const token = (await getToken()) ?? undefined;

// 1) Upload: authenticated presign intent -> PUT -> ownership registration -> key
const { key } = await api.presignAndUpload(file, {
  token,
  onProgress: (f) => setUploadPct(Math.round(f * 100)),
});

// 2) Create the job with that key as screen_recording_key
const params: ReelForgeParams = {
  video_subject: "How I edit reels in 10 minutes",
  voice_name: "elevenlabs:<voice_id>",
  avatar_id: "<avatar_id>",
  avatar_provider: "heygen",
  caption_style: "default",
  layout: "pip",
  aspect: "9:16",
  language: "auto",
  target_duration_s: 30,
  platforms: [],
  screen_recording_key: key,
};
const job = await api.createJob({ params }, { token });

// 3) Poll every 3s until the job is terminal
await api.pollJob(job.job_id, (j) => setProgress(j.progress), { token });
```

The browser product uses canonical `/jobs` and `/generation/broll/*` workflows,
including capability discovery, direct-to-R2 uploads, signed previews, polling,
and B-roll-to-reel attachment. Both paid create commands retain a stable
idempotency key until the API has accepted the request.

The `/media/playground` product flow uses the unified media gateway for image,
video, and audio generation against one wallet balance. A completed image can
be carried directly into the video form with **Animate image**; the client
prefers an image-to-video model, passes the result URL as `image_url`, keeps the
cost pre-flight visible, and polls the video to a terminal result.

Completed jobs link into `/editor?job=<id>`. The editor reads the same
authenticated job contract, previews an in/out range, and submits an idempotent
`POST /jobs/{id}/exports` command. The resulting `editor_export` is polled and
downloaded like every other job; FFmpeg runs on the render worker and no second
editor database or unsigned media path is introduced.

## Deploying to Cloudflare Workers (OpenNext)

This app deploys to **Cloudflare Workers** via
[`@opennextjs/cloudflare`](https://opennext.js.org/cloudflare) (the successor to
the deprecated `@cloudflare/next-on-pages`). The adapter runs `next build` and
then bundles a Worker at `.open-next/worker.js`, which
[`wrangler.jsonc`](./wrangler.jsonc) points to via `main`.

```bash
npm run cf:build     # opennextjs-cloudflare build  -> .open-next/worker.js + .open-next/assets
npm run cf:preview   # run the built Worker locally in workerd
npm run cf:deploy    # build + wrangler deploy (requires Cloudflare account credentials)
```

- Worker entry: `.open-next/worker.js`; static assets: `.open-next/assets`
  (the `ASSETS` binding). Both are declared in `wrangler.jsonc`.
- Config: [`open-next.config.ts`](./open-next.config.ts) uses the adapter's
  in-memory incremental cache (`routePreloadingBehavior: "none"`); add an
  R2-backed `incrementalCache` there if ISR/data-cache persistence is needed.
- Runtime flags: `nodejs_compat` + `global_fetch_strictly_public`
  (compatibility date `2026-08-23`).
- Public env vars live in `wrangler.jsonc` `vars`; **secrets** (e.g.
  `CLERK_SECRET_KEY`) must be set as Worker secrets, not committed:
  `npx wrangler secret put CLERK_SECRET_KEY`.
- Version note: the app is pinned to `@opennextjs/cloudflare@1.20.2`, the highest
  release whose `next` peer range (`>=15.5.21 <16`) is satisfied by the installed
  Next `15.5.23`. Bump Next to `>=15.5.24` before moving to `@opennextjs/cloudflare`
  `>=1.20.3`.

> Unlike `next-on-pages`, OpenNext runs Next's Node.js server on Workers, so
> route handlers do **not** need `export const runtime = "edge"`.

## Clerk Frontend API proxy (fallback for clerk.menivor.com)

If the Clerk Frontend API custom domain (`clerk.menivor.com`) fails (for
example Cloudflare error 1000/403 because Clerk's domain verification or SSL
never completed), sign-up cannot load. Clerk's documented fallback is to
serve the Frontend API from the app's own domain:
<https://clerk.com/docs/guides/dashboard/dns-domains/proxy-fapi>.

What is in the code:

- `middleware.ts` forwards every `/__clerk/*` request to
  `https://frontend-api.clerk.dev/*` (`lib/clerk-proxy.ts`). It sets
  `Clerk-Proxy-Url`, `Clerk-Secret-Key` (from the `CLERK_SECRET_KEY` Worker
  secret) and `X-Forwarded-For` (from `cf-connecting-ip`), strips hop-by-hop
  headers and any client-sent Clerk headers, streams bodies both ways, keeps
  every `Set-Cookie`, and passes redirects through. The forwarder is always
  deployed, but nothing uses it until the switch below.
- `ClerkProvider` (`app/layout.tsx`) and `clerkMiddleware` get
  `proxyUrl` only when `NEXT_PUBLIC_CLERK_PROXY_URL` is set (`lib/clerk.ts`,
  https URLs only). Unset = current behaviour (`clerk.menivor.com`).

One-time switch (owner, in this order):

1. Deploy this code as usual (`npm run cf:deploy`) so `https://menivor.com/__clerk`
   is live.
2. Point the Clerk production domain at the proxy, either in the Clerk
   dashboard (Domains -> Frontend API -> Set proxy configuration ->
   `https://menivor.com/__clerk`) or via the Backend API:

   ```bash
   curl -X PATCH https://api.clerk.com/v1/domains/<DOMAIN_ID> \
     -H "Authorization: Bearer $CLERK_SECRET_KEY" \
     -H "Content-Type: application/json" \
     -d '{"proxy_url": "https://menivor.com/__clerk"}'
   ```

   (`GET https://api.clerk.com/v1/domains` lists the domain id.)
3. Set `NEXT_PUBLIC_CLERK_PROXY_URL=https://menivor.com/__clerk` in BOTH
   `apps/web/.env.local` (inlined at build time for the browser) and the
   `vars` block of `wrangler.jsonc` (read at runtime by the middleware), then
   rebuild and redeploy.
4. Check: `https://menivor.com/sign-up` renders the Clerk form and the browser
   network tab shows requests to `menivor.com/__clerk/...`, not
   `clerk.menivor.com`.

To roll back, remove `NEXT_PUBLIC_CLERK_PROXY_URL` from both places, clear the
proxy URL on the Clerk domain, and redeploy.

## Security — secret rotation (ACTION REQUIRED)

`.env.local` is gitignored (`.env*.local`) and is **not** tracked in git, but it
currently holds **live** production credentials on this machine:

- A live Clerk **secret** key (`sk_live_…`) and publishable key (`pk_live_…`) for
  the `clerk.menivor.com` production instance.
- A live `REPLICATE_API_TOKEN` (`r8_…`).

These cannot be rotated from this repo. The owner must:

1. **Rotate the Clerk secret key** in the Clerk dashboard
   (https://dashboard.clerk.com → API Keys) — assume the current `sk_live_…` is
   compromised since it has sat in a local dotenv. The publishable `pk_live_…` is
   browser-safe and does not need rotation.
2. **Rotate the `REPLICATE_API_TOKEN`** at https://replicate.com/account/api-tokens.
3. Store the new secrets in a secret manager, **not** in `.env.local`:
   - For the deployed Worker: `npx wrangler secret put CLERK_SECRET_KEY`.
   - For CI/local: use the platform secret store; keep `.env.example`
     placeholders only.

`.env.example` intentionally contains empty placeholders for all Clerk keys.
