# @menivor/sdk (TypeScript)

Small `fetch`-based client for the Menivor `/api/v1` platform.

- No transport runtime dependency (uses platform `fetch`; Node 18+, Deno, Bun, browsers).
- Canonical generation types come from `@reelforge/api-contract`.
- Unwraps the `{ status, data }` envelope and throws `MenivorApiError` on non-2xx.

## Install

> **Not on npm yet.** The `@menivor/sdk` package name is reserved in-repo; until it
> is published, install from this repository (`npm install ./packages/sdk-typescript`
> after `npm run build` there). The older `ReelForgeClient` / `ReelForgeApiError`
> exports remain as aliases of `MenivorClient` / `MenivorApiError`.

```bash
npm install @menivor/sdk
```

## Quickstart

```ts
import { MenivorClient } from "@menivor/sdk";

const rf = new MenivorClient({
  apiKey: process.env.MENIVOR_API_KEY!, // never hardcode secrets
  baseUrl: "https://api.menivor.com",   // optional
});

// Current user
const me = await rf.me();
console.log(me.email, me.credits);

// Create a job and poll it
const job = await rf.createJob(
  { params: { script: "hello world" } },
  { idempotencyKey: crypto.randomUUID() },
);
const status = await rf.getJob(job.job_id);
const cut = await rf.exportEditorCut(
  job.job_id,
  { in_point: 1.5, out_point: 8 },
  { idempotencyKey: crypto.randomUUID() },
);

// Resource-group form is also available.
const generations = await rf.broll.list();
const broll = await rf.generateBroll(
  { prompt: "Slow dolly through a bright studio", mode: "t2v" },
  { idempotencyKey: crypto.randomUUID() },
);

// Presign an upload
const presign = await rf.presignUpload({
  filename: "clip.mp4",
  content_type: "video/mp4",
  size: 1048576,
});

// Webhook subscriptions (the signing secret is returned ONCE, on create)
const sub = await rf.createWebhookSubscription("ws_123", {
  url: "https://example.com/hooks/reelforge",
  event_types: ["job.completed", "publish.succeeded"],
});
console.log("store this now:", sub.secret);

await rf.testWebhookSubscription("ws_123", sub.id);
const deliveries = await rf.listWebhookDeliveries("ws_123", sub.id, 20);

// Developer portal + usage
const portal = await rf.getDeveloperPortal();
const usage = await rf.getUsage("ws_123", "2026-08");
```

## Error handling

```ts
import { MenivorApiError } from "@menivor/sdk";

try {
  await rf.getJob("does-not-exist");
} catch (err) {
  if (err instanceof MenivorApiError) {
    console.error(err.status, err.message); // e.g. 404, "job not found"
  }
}
```

## API surface

| Method | Route |
| --- | --- |
| `me()` | `GET /me` |
| `createJob(body)` | `POST /jobs` |
| `getJob(id)` | `GET /jobs/{id}` |
| `listJobs({ limit, offset })` | `GET /jobs` |
| `retryJob(id)` | `POST /jobs/{id}/retry` |
| `rerunJob(id, body)` | `POST /jobs/{id}/rerun` |
| `getBatch(id)` | `GET /batches/{id}` |
| `exportEditorCut(id, body)` | `POST /jobs/{id}/exports` |
| `generateBroll(body)` | `POST /generation/broll/generate` |
| `getBrollGeneration(id)` | `GET /generation/broll/generations/{id}` |
| `listBrollGenerations()` | `GET /generation/broll/generations` |
| `presignUpload(body)` | `POST /uploads/presign` |
| `createWebhookSubscription(ws, body)` | `POST /me/workspaces/{ws}/webhooks` |
| `listWebhookSubscriptions(ws)` | `GET /me/workspaces/{ws}/webhooks` |
| `deleteWebhookSubscription(ws, id)` | `DELETE /me/workspaces/{ws}/webhooks/{id}` |
| `testWebhookSubscription(ws, id)` | `POST /me/workspaces/{ws}/webhooks/{id}/test` |
| `listWebhookDeliveries(ws, id, limit?)` | `GET /me/workspaces/{ws}/webhooks/{id}/deliveries` |
| `getDeveloperPortal()` | `GET /me/developer` |
| `getUsage(ws, period?)` | `GET /me/workspaces/{ws}/usage` |
| `getEntitlements(ws)` | `GET /me/workspaces/{ws}/entitlements` |

### Media gateway (OpenRouter-style — one key, one balance)

`client.media.*` — every image and video model behind a single key and wallet balance.

| Method | Route |
| --- | --- |
| `media.listModels(modality?)` | `GET /media/models` |
| `media.createImage({ model, prompt })` | `POST /media/images` (sync → `{ url }`) |
| `media.createVideo({ model, prompt, duration? })` | `POST /media/videos` (async job) |
| `media.getVideo(id)` | `GET /media/videos/{id}` |
| `media.waitForVideo(body)` | submit + poll to terminal |
| `media.createAudio({ model, prompt, instrumental? })` | `POST /media/audio` (async job — Suno music) |
| `media.getAudio(id)` | `GET /media/audio/{id}` |
| `media.credits()` | `GET /media/credits` |
| `media.usage(limit?)` | `GET /media/usage` |
| `media.generation(id)` | `GET /media/generation/{id}` |

```ts
const { url } = await rf.media.createImage({ model: "openai/gpt-image-1", prompt: "a red panda" });
const video = await rf.media.waitForVideo({ model: "kwaivgi/kling-v1.6", prompt: "surfing", duration: 5 });
const { available_micros } = await rf.media.credits();
```

## Verify

```bash
npm --workspace @menivor/sdk run typecheck
```

## License

MIT
