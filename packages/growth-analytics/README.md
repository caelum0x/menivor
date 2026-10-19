# @reelforge/growth-analytics

Pure client-and-server analytics: **retention-curve normalization + reach-tier
mapping, hook-strength scoring vs the 70% gate, and retention-weighted A/B winner
selection**. No I/O — takes data, returns verdicts — so web, mobile and the
Python backend compute identical numbers (golden fixtures).

## API

```ts
import { normalizeCurve, reachTier, dropoff, hookScore, selectWinner } from "@reelforge/growth-analytics";

normalizeCurve([1000, 820, 610]);          // → [1, 0.82, 0.61]
reachTier(0.9);                            // → { tier: "viral", multiplier: 3 }
hookScore({ motion: 0.9, contrast: 0.8, text: 0.7, audio_onset: 0.8 }); // { score, passes }
selectWinner([{ id: "A", completion: 0.5, avg_watch: 12 }, { id: "B", completion: 0.42, avg_watch: 18 }]);
// → picks B: retention-weighted, not vanity views
```

```python
from reelforge_growth_analytics import reach_tier, hook_score, select_winner
```

- **reach tiers:** `<70%` minimal (1×) · `70–85%` boosted (2.2×) · `≥85%` viral (3×)
- **hook gate:** weighted first-3s signals (motion .35 / contrast .2 / text .2 / audio-onset .25) vs 0.70
- **A/B winner:** `0.6·completion + 0.4·(avg_watch / max_avg_watch)`

## Parity

Bit-identical via a shared `round6`. `test/fixtures/golden/analytics.json` is the contract.

```bash
PYTHONPATH=python python -m pytest test -q
npm run build && npm run test:parity
```
