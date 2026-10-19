# @reelforge/comfy-workflow-schema

Contract for treating ComfyUI graphs as **pinned, versioned artifacts** — node
commits + weight refs + a typed input contract, locked per version. Shared so the
render-farm registry, the provider adapters, and the desktop/agency endpoint all
reference the same **immutable workflow identity**.

The pin is a deterministic **FNV-1a-32** hash over the canonical identity, so any
change to node commits, weight refs, or the input contract yields a new version —
byte-identical across the TS and Python ports.

## Use

```ts
import { getWorkflow, graphHash, validateInputs } from "@reelforge/comfy-workflow-schema";
const w = getWorkflow("wan-i2v");
graphHash(w);                                   // "9ea52ffd" — immutable pin
validateInputs(w, { image: "x.png", frames: 81 }); // [] when valid
```

```python
from reelforge_comfy_workflow import get_workflow, graph_hash, validate_inputs
graph_hash(get_workflow("wan-i2v"))  # "9ea52ffd"
```

First-party workflows: `wan-i2v` · `flux-first-frame` · `lipsync-musetalk`.

## Parity

`test/fixtures/golden/workflows.json` pins each descriptor, its FNV-1a hash, and
validation outcomes.

```bash
PYTHONPATH=python python -m pytest test -q
npm run build && npm run test:parity
```
