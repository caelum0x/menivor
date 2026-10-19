# @reelforge/shot-template-schema

Canonical schema for genre templates as **named segment slots** (Hook / Setup /
Rising / Payoff / Loop / CTA) bound to caption presets + transitions. This is the
contract the backend `templates/` domain seeds into the DB and the frontends
render in the picker — one definition, no drift.

Slot times are **integer milliseconds**, so the deterministic **FNV-1a content
hash** (used for immutable instance pinning) is byte-identical across the TS and
Python ports.

## Use

```ts
import { getPreset, validateTemplate, contentHash, listPresets } from "@reelforge/shot-template-schema";
const t = getPreset("minecraft-reddit-split");
validateTemplate(t);   // [] when valid (roles in order, no gaps/overlaps)
contentHash(t);        // e.g. "b3de1da5" — same in Python
```

```python
from reelforge_shot_template import get_preset, validate_template, content_hash
content_hash(get_preset("minecraft-reddit-split"))  # "b3de1da5"
```

Seed presets: `minecraft-reddit-split` · `asmr-loop` · `movie-recap` ·
`platform-hook-open` · `fake-podcast`.

## Parity

`test/fixtures/golden/templates.json` pins each preset's slots, validity, and
FNV-1a hash.

```bash
PYTHONPATH=python python -m pytest test -q
npm run build && npm run test:parity
```
