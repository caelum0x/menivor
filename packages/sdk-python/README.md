# menivor (Python SDK)

Tiny, standard-library-only client for the Menivor `/api/v1` platform.

- No required dependencies — uses `httpx` when installed, else `urllib` from the stdlib.
- Typed methods that unwrap the `{ "status", "data" }` envelope.
- Raises `MenivorApiError` (with `.status` + `.message`) on non-2xx.

## Install

> **Not on PyPI yet.** The `menivor` distribution name is reserved in-repo; until it
> is published, install from this repository (`pip install ./packages/sdk-python`).
> `import reelforge_sdk` and the `ReelForge*` names keep working as aliases.

```bash
pip install menivor           # stdlib transport
pip install "menivor[httpx]"        # optional pooled httpx transport
```

## Quickstart

```python
import os
from menivor import MenivorClient

rf = MenivorClient(api_key=os.environ["MENIVOR_API_KEY"])  # never hardcode secrets

# Current user
me = rf.me()
print(me["email"], me["credits"])

# Create a job and poll it
job = rf.create_job(
    {"params": {"script": "hello world"}},
    idempotency_key="create-reel-01",
)
status = rf.get_job(job["job_id"])
cut = rf.export_editor_cut(
    job["job_id"], in_point=1.5, out_point=8, idempotency_key="cut-01"
)

# Resource-group form is also available.
generations = rf.broll.list()
broll = rf.generate_broll(
    {"prompt": "Slow dolly through a bright studio", "mode": "t2v"},
    idempotency_key="broll-01",
)

# Presign an upload
presign = rf.presign_upload(
    {"filename": "clip.mp4", "content_type": "video/mp4", "size": 1048576}
)

# Webhook subscriptions (the signing secret is returned ONCE, on create)
sub = rf.create_webhook_subscription(
    "ws_123",
    url="https://example.com/hooks/reelforge",
    event_types=["job.completed", "publish.succeeded"],
)
print("store this now:", sub["secret"])

rf.test_webhook_subscription("ws_123", sub["id"])
deliveries = rf.list_webhook_deliveries("ws_123", sub["id"], limit=20)

# Developer portal + usage
portal = rf.get_developer_portal()
usage = rf.get_usage("ws_123", period="2026-08")
```

Use it as a context manager to close the pooled transport cleanly:

```python
with MenivorClient(api_key="rf_...") as rf:
    me = rf.me()
```

## Error handling

```python
from menivor import MenivorApiError

try:
    rf.get_job("does-not-exist")
except MenivorApiError as err:
    print(err.status, err.message)  # e.g. 404, "job not found"
```

## API surface

| Method | Route |
| --- | --- |
| `me()` | `GET /me` |
| `create_job(body)` | `POST /jobs` |
| `get_job(id)` | `GET /jobs/{id}` |
| `list_jobs(limit, offset)` | `GET /jobs` |
| `retry_job(id)` | `POST /jobs/{id}/retry` |
| `rerun_job(id, body)` | `POST /jobs/{id}/rerun` |
| `get_batch(id)` | `GET /batches/{id}` |
| `export_editor_cut(id, in_point, out_point)` | `POST /jobs/{id}/exports` |
| `generate_broll(body)` | `POST /generation/broll/generate` |
| `get_broll_generation(id)` | `GET /generation/broll/generations/{id}` |
| `list_broll_generations()` | `GET /generation/broll/generations` |
| `presign_upload(body)` | `POST /uploads/presign` |
| `create_webhook_subscription(ws, url, event_types)` | `POST /me/workspaces/{ws}/webhooks` |
| `list_webhook_subscriptions(ws)` | `GET /me/workspaces/{ws}/webhooks` |
| `delete_webhook_subscription(ws, id)` | `DELETE /me/workspaces/{ws}/webhooks/{id}` |
| `test_webhook_subscription(ws, id)` | `POST /me/workspaces/{ws}/webhooks/{id}/test` |
| `list_webhook_deliveries(ws, id, limit)` | `GET /me/workspaces/{ws}/webhooks/{id}/deliveries` |
| `get_developer_portal()` | `GET /me/developer` |
| `get_usage(ws, period)` | `GET /me/workspaces/{ws}/usage` |
| `get_entitlements(ws)` | `GET /me/workspaces/{ws}/entitlements` |

### Media gateway (OpenRouter-style — one key, one balance)

`client.media.*` — every image and video model behind a single key and wallet balance.

| Method | Route |
| --- | --- |
| `media.list_models(modality=None)` | `GET /media/models` |
| `media.create_image(model, prompt)` | `POST /media/images` (sync → `{ "url" }`) |
| `media.create_video(model, prompt, duration=5)` | `POST /media/videos` (async job) |
| `media.get_video(id)` | `GET /media/videos/{id}` |
| `media.wait_for_video(model, prompt, ...)` | submit + poll to terminal |
| `media.create_audio(model, prompt, instrumental=False)` | `POST /media/audio` (async job — Suno music) |
| `media.get_audio(id)` | `GET /media/audio/{id}` |
| `media.credits()` | `GET /media/credits` |
| `media.usage(limit=None)` | `GET /media/usage` |
| `media.generation(id)` | `GET /media/generation/{id}` |

```python
img = client.media.create_image(model="openai/gpt-image-1", prompt="a red panda")
video = client.media.wait_for_video(model="kwaivgi/kling-v1.6", prompt="surfing", duration=5)
credits = client.media.credits()
```

## Verify

```bash
PYTHONPATH=packages/sdk-python python -c 'import reelforge_sdk'
```

## License

MIT
