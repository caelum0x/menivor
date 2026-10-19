# @reelforge/eventbus-types

The shared **event catalog** — canonical event names, the `EventEnvelope` shape,
and the event→push/deep-link mapping — so the backend outbox, the SDK webhook
types, and the client notification router all agree. Transport (outbox/dispatch)
stays in `apps/api`; only the schema is shared.

## Events

`job.completed` · `job.failed` · `publish.succeeded` · `publish.failed` ·
`retention.ingested` · `performance.ingested` · `experiment.winner_selected` ·
`gateway.key_spend_exceeded` · `gateway.plan_changed` ·
`marketplace.submission_approved` · `marketplace.payout_paid`

## Use

```ts
import { makeEnvelope, pushFor, isEventType } from "@reelforge/eventbus-types";
const env = makeEnvelope("job.completed", { job_id: "j1" }, { id: "evt-1", occurred_at: iso });
pushFor("job.completed"); // { channel: "push", title: "Your reel is ready", deep_link: "/jobs/{job_id}" }
```

```python
from reelforge_eventbus import make_envelope, push_for
env = make_envelope("job.completed", {"job_id": "j1"}, id="evt-1", occurred_at=iso)
```

## Parity

`test/fixtures/golden/events.json` pins the catalog + push map + sample envelopes.

```bash
PYTHONPATH=python python -m pytest test -q
npm run build && npm run test:parity
```
