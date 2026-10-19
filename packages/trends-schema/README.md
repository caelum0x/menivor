# @reelforge/trends-schema

Canonical trend/sound DTOs + **pure saturation / velocity / decay / opportunity
scoring**, so the trend feed reads identically on backend, web and mobile.
Scrapers stay in `apps/api`; the scoring math is shared and byte-identical
across the TypeScript and Python ports (golden fixtures).

## Scoring

Given a usage series (e.g. daily plays), `score(series)` returns:

| field | meaning |
|---|---|
| `saturation` | current / peak (1.0 = at peak, over-saturated) |
| `velocity` | normalized recent adoption step (sign = rising/falling) |
| `decay` | fraction fallen from a past peak |
| `opportunity` | composite "ride it now" score ∈ [0,1] |

Plus `adSafe(sound)` — cross-platform (Meta-compatible) ad-safe rule.

```ts
import { score, adSafe } from "@reelforge/trends-schema";
score([2, 5, 9, 15, 24, 40]);          // { saturation, velocity, decay, opportunity }
adSafe({ licensed: true, explicit: false }); // true
```

```python
from reelforge_trends import score, ad_safe
score([2, 5, 9, 15, 24, 40])
```

## Parity

Bit-identical output is guaranteed by a shared `round6` (same IEEE-754 op
sequence). `test/fixtures/golden/scores.json` is the contract.

```bash
PYTHONPATH=python python -m pytest test -q
npm run build && npm run test:parity
```
