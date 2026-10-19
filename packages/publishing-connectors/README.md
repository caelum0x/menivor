# @reelforge/publishing-connectors

A dependency-light **client SDK** wrapping each platform's publish API behind one
`Publisher` interface, plus the shared **policy** the whole product agrees on:
per-platform **caps**, **foreign-watermark cross-post rules**, and **OAuth config**.

> **Security seam.** Connectors are stateless — tokens are passed **in** per call
> (the API decrypts Fernet tokens and injects them); nothing is read from env/store.

The caps / watermark / oauth tables are byte-identical across the TS and Python
ports (golden fixtures) so the cap-aware composer (web/mobile) and the publish
policy (api) never disagree.

## Use

```ts
import { validatePublish, checkWatermark, scopeString } from "@reelforge/publishing-connectors";

validatePublish("youtube", { duration_s: 200, aspect: "9:16", caption_len: 50 });
// ["youtube: duration 200s over max 180s"]

checkWatermark("instagram", "tiktok");
// { allowed: false, reason: "tiktok watermark is suppressed on instagram; re-export …" }

scopeString("tiktok"); // "user.info.basic video.publish video.upload"
```

The four `Publisher` clients (`TikTokPublisher`, `InstagramPublisher`,
`YouTubePublisher`, `XPublisher`), the `httpJson` transport, and the
`createPublisher` factory are available from both ports, so a Python consumer can
**publish**, not merely read policy:

```python
from reelforge_publishing_connectors import (
    validate_publish, check_watermark, create_publisher, PublishRequest,
)

pub = create_publisher("tiktok")
req = PublishRequest(video_url=presigned_r2_url, caption="…", aspect="9:16", duration_s=28)
result = pub.publish(req, access_token)   # token injected per call, never persisted
# PublishResult(platform="tiktok", post_id="…", url="https://www.tiktok.com/@me/video/…")
```

The clients are stateless and share one dependency-free HTTP+JSON transport
(`http_json`, stdlib `urllib`); pass a fake `http` into any client constructor to
capture request shapes in tests.

Platforms: `tiktok` · `instagram` · `youtube` · `x`.

## Parity

Two golden fixtures pin TS≡Python behaviour:

- `test/fixtures/golden/connectors.json` — caps / validation / watermark / oauth.
- `test/fixtures/golden/clients.json` — per-client request shapes + normalized
  results for `publish` / `refresh` / `fetchAnalytics`.

```bash
PYTHONPATH=python python -m pytest test -q          # policy + client parity (Python)
npm run build && npm run test:parity                # policy + client parity (TS)
```
