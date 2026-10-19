# @reelforge/effects-core

Shared **camera + VFX preset kernels** for ReelForge — the `vfx.py` concepts
extracted so the effect picker / live preview (web, mobile) and the render
executor (`app/services/compose/vfx.py`) apply **identical math**.

Every kernel is a pure function `apply(t, params) -> output` over normalized time
`t ∈ [0,1]`, built from **pure polynomial / 32-bit-integer** primitives only (no
`sin`/`pow` float transcendentals) so the TypeScript and Python ports are
**bit-identical** — verified by golden fixtures.

## Kernels

| id | category | output |
|---|---|---|
| `push-in` | camera | `{ zoom }` — eased push-in |
| `ken-burns` | camera | `{ zoom, x, y }` — pan + zoom over a still |
| `handheld` | camera | `{ dx, dy, rot }` — deterministic micro-shake |
| `rgb-split` | vfx | `{ shift_px }` — chromatic aberration, peaks mid |
| `film-grain` | vfx | `{ grain, vignette }` |
| `shake` | vfx | `{ amplitude }` — impact shake, decays |

## Use

```ts
import { apply, listKernels } from "@reelforge/effects-core";
listKernels("camera");            // ["handheld","ken-burns","push-in"]
apply("push-in", 0.5);            // { zoom: 1.15 }
```

```python
from reelforge_effects_core import registry
registry.apply("push-in", 0.5)   # {"zoom": 1.15}
```

## FFmpeg bridge (`ffexpr`)

The render executor (`app/services/compose/vfx.py`) can't sample a numeric kernel
per frame — FFmpeg needs the curve as a **filter expression**. `ffexpr` renders
the exact same kernel math as FFmpeg expression strings (parameterized by a
normalized-time sub-expression `tn`), so a rendered frame lands the value the
preview showed:

```python
from reelforge_effects_core import ffexpr
ffexpr.push_in_zoom_expr("(t/6)", intensity=0.12)  # -> "(1+0.12*(if(lt(...))))"
ffexpr.evaluate(ffexpr.push_in_zoom_expr("t"), {"t": 0.5})  # 1.15  == registry.apply("push-in",0.5)
```

`vfx.py` splices these into a `scale=...:eval=frame` / `crop` / `rotate` chain for
the camera presets in `vfx.KERNEL_BY_PRESET`. `evaluate()` models FFmpeg's
expression semantics over a whitelisted op set, so parity is proven without a real
FFmpeg process (`test/test_ffexpr.py`, and the TS side in `test/parity.mjs`).

## Parity

`test/fixtures/golden/kernels.json` is the canonical output, generated from the
Python port. Both ports are checked against it:

```bash
# Python side
PYTHONPATH=python python -m pytest test -q
# TypeScript side (build then run the golden harness)
npm run build && npm run test:parity
```
