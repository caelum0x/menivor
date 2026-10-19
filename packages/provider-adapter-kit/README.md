# provider-adapter-kit 0.2.0

The shared **adapter contract + metadata**: license classes, the deprecation /
sunset registry, and the async job envelope grammar — extracted so the routing
engine (Python), the SDKs, and the burn-preview UIs agree on model identity,
license class, and sunset dates without duplication. Provider HTTP behavior may
implement the pure Python execution protocol; persistence, credentials, retry
scheduling, and wallet settlement stay in the consuming application.

The package is independently installable from this directory. The metadata and
async state grammar remain byte-identical in TypeScript/Python. The v1 execution
DTOs are currently Python-first because the API and Prism integration boundary
is Python.

## Provider execution v1

```python
from reelforge_provider_adapter import (
    ProviderCostV1,
    ProviderHandleV1,
    ProviderOutputV1,
    ProviderResultV1,
)

handle = ProviderHandleV1(
    provider_key="runway",
    model_ref="runwayml/gen-4",
    run_id="task_123",
    state="COMPLETED",
    opaque={"poll_token": "provider-opaque-not-a-secret"},
)
result = ProviderResultV1(
    handle=handle,
    outputs=(ProviderOutputV1("https://cdn.example/video.mp4", "video", "video/mp4"),),
    cost=ProviderCostV1(True, 420_000, source="provider_reported"),
)
```

Schemas are explicit:

- request: `menivor.provider-execution/v1`
- durable handle: `menivor.provider-handle/v1`
- result: `menivor.provider-result/v1`

Completed results require a validated HTTP(S) output or a bounded inline image
and successful cost semantics. Inline output accepts only valid base64 PNG,
JPEG, or WebP data up to 16 MiB decoded. In-flight, failed, and cancelled
outcomes are never billable. A
typed error records its phase, category, retryability, and whether the provider
definitely did, definitely did not, or may have accepted the request.

`should_fail_over(error)` permits failover only for a retryable submit failure
known not to have been accepted. `decode_legacy_execution(...)` safely upgrades
the former Prism `ExecutionOutcome` mapping while retaining unknown polling
fields in the handle's `opaque` object. `ProviderExecutorRegistry` resolves
executors and rejects provider/model/run identity drift across submit, poll,
and cancel; it deliberately owns no persistence or retry policy.

## License classes

`commercial-safe` (usable for paid output) · `non-commercial` (research only) ·
`territorial` (commercial-OK with regional/scale caveats — gate). Unknown models
default to `territorial`.

```ts
import { canUseForPaid, migrate, normalizeState } from "@reelforge/provider-adapter-kit";
canUseForPaid("black-forest-labs/flux-dev");   // false (non-commercial)
migrate("openai/sora-2", "2026-10-01");         // { status: "sunset", replacement: "google/veo-3.1", ... }
normalizeState("DREAMING");                     // "IN_PROGRESS"
```

```python
from reelforge_provider_adapter import can_use_for_paid, migrate, normalize_state
```

## Deprecation

ISO sunset dates compare lexicographically, so `today` is a **parameter** (no
hidden clock): `active` → `deprecating` (announced) → `sunset` (≥ date), with a
recommended replacement.

## Parity

`test/fixtures/golden/adapter.json` pins license / deprecation / envelope / usage.

```bash
python -m pip install -e .
python -m pytest test -q
npm run build && npm run test:parity
```
