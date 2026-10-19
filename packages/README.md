# ReelForge shared packages

The shared API contract plus thin, dependency-light clients for the ReelForge
`/api/v1` platform. Both SDKs expose resource groups for jobs, B-roll,
presigned uploads, editor exports, webhooks, and workspaces while retaining
their original top-level convenience methods. They authenticate with a per-user
API key (`x-api-key`), unwrap the `{ status, data }` response envelope, and
raise a typed error on non-2xx. Typed errors retain the API's
`X-Correlation-ID` so support can trace failures that happen before job creation.
Direct-upload integrations must call `uploads.presign`, PUT to the returned
signed URL, then call `uploads.register`; ownership is reserved by the API at
presign time and cannot be claimed by another principal afterward.

| Kind | Package | Directory | Role/transport |
| --- | --- | --- | --- |
| Contract | `@reelforge/api-contract` | [`api-contract/`](./api-contract) | Deterministic OpenAPI, generated TypeScript DTOs, shared job/error/capability semantics |
| TypeScript | `@menivor/sdk` | [`sdk-typescript/`](./sdk-typescript) | global `fetch`, zero deps |
| Python | `menivor` | [`sdk-python/`](./sdk-python) | `httpx` if present, else stdlib `urllib` |

Both are MIT-licensed. Neither is published to npm/PyPI yet; install from this
repository until they are. The legacy `ReelForge*` export names remain as aliases.

## Authentication

Create an API key in the Menivor dashboard (Settings → API Keys) and provide it
to the client. **Never hardcode secrets** — read them from the environment.

## TypeScript quickstart

```ts
import { MenivorClient } from "@menivor/sdk";

const rf = new MenivorClient({ apiKey: process.env.MENIVOR_API_KEY! });

const me = await rf.me();
const job = await rf.createJob({ params: { script: "hello world" } });
const status = await rf.getJob(job.job_id);
const cut = await rf.exportEditorCut(job.job_id, { in_point: 1.5, out_point: 8 });

const sub = await rf.createWebhookSubscription("ws_123", {
  url: "https://example.com/hooks/reelforge",
  event_types: ["job.completed"],
});
console.log("one-time signing secret:", sub.secret);
```

Verify: `npm --workspace @menivor/sdk run typecheck`

## Python quickstart

```python
import os
from menivor import MenivorClient

rf = MenivorClient(api_key=os.environ["MENIVOR_API_KEY"])

me = rf.me()
job = rf.create_job({"params": {"script": "hello world"}})
status = rf.get_job(job["job_id"])
cut = rf.export_editor_cut(job["job_id"], in_point=1.5, out_point=8)

sub = rf.create_webhook_subscription(
    "ws_123",
    url="https://example.com/hooks/reelforge",
    event_types=["job.completed"],
)
print("one-time signing secret:", sub["secret"])
```

Verify: `python -c 'import sys; sys.path.insert(0,"packages/sdk-python"); import menivor'`

## Webhooks

Subscriptions are workspace/tenant-scoped. On create, the HMAC signing secret is
returned **exactly once** — store it immediately; list, get, and delivery views
never return it again. Each delivery is HMAC-signed and carries a unique delivery
id for idempotent, dedupe-friendly processing. Subscription URLs must be public
(the platform rejects internal/private/loopback targets), so point them at a
publicly reachable HTTPS endpoint.

**Signatures (Standard Webhooks).** Every delivery is signed per
[Standard Webhooks](https://www.standardwebhooks.com) with three headers:

| Header | Value |
| --- | --- |
| `webhook-id` | Message id; the same on every retry of one delivery (it equals the body's `event_id`). Dedupe on it. |
| `webhook-timestamp` | Unix seconds of THIS attempt; each retry is re-signed with a fresh timestamp. |
| `webhook-signature` | `v1,<base64 HMAC-SHA256 of "{webhook-id}.{webhook-timestamp}.{raw body}">` (space-separated list; accept if any `v1` entry matches). |

The HMAC key is your signing secret exactly as shown at creation, used as its
raw UTF-8 bytes. Menivor secrets are not `whsec_`-prefixed base64: do not
base64-decode them (if you use a Standard Webhooks library, give it the raw key
bytes). Reject a delivery whose `webhook-timestamp` is more than 5 minutes from
your clock (stale or in the future), compare signatures in constant time, and
verify against the raw request body before parsing it.

```python
import base64, hashlib, hmac, time

def verify(secret: str, headers: dict, body: bytes, tolerance_s: int = 300) -> bool:
    h = {k.lower(): v for k, v in headers.items()}
    msg_id, ts, sigs = h.get("webhook-id"), h.get("webhook-timestamp"), h.get("webhook-signature", "")
    if not (msg_id and ts and sigs) or abs(int(time.time()) - int(ts)) > tolerance_s:
        return False
    mac = hmac.new(secret.encode(), f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode()
    return any(v == "v1" and hmac.compare_digest(s, expected)
               for v, _, s in (t.partition(",") for t in sigs.split()))
```

**Deprecated body-only header (transition window).** Deliveries still carry
`X-Menivor-Signature: sha256=<hexdigest>` (HMAC-SHA256 of the raw body only,
same secret) and its older alias `X-ReelForge-Signature` with the identical
value, so existing receivers keep working. They carry no timestamp, so they do
not protect against replays: move to the `webhook-*` headers. Only fall back to
the body-only header when the `webhook-*` headers are absent. Both body-only
headers will be removed in a later release, announced on the developer page
first. (The server-side reference check is
`app.services.webhooks.verify_signature`.)

Supported event types: `job.completed`, `publish.succeeded`, `publish.failed`,
`performance.ingested` (also exported as `WEBHOOK_EVENT_TYPES` in both SDKs).

## Errors

Both clients raise a typed error carrying the HTTP status and the server message:
`MenivorApiError` (TypeScript, with `.status` / `.body`) and `MenivorApiError`
(Python, with `.status` / `.message` / `.body`).
