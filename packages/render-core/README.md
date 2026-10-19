# @reelforge/render-core

Declarative **RenderSpec** → FFmpeg `filter_complex` string. The client uses it
for preview + to serialize the spec to the API; the Python worker
(`app/services/compose/compose_ffmpeg.py`) is the executor. This library
reproduces the executor's **composition graph** (everything up to the `[comp]`
sink) and its **ducked-audio graph** (`[aout]`) **byte-for-byte**, so preview
matches output.

> `render-core` owns spec→string only. It never spawns processes or touches
> storage — the Celery worker + FFmpeg remain the only executor.

## What is (and isn't) in the shared byte-identical contract

| Fragment | Shared? | Why |
| --- | --- | --- |
| Layout composition → `[comp]` (`captions_only` / `pip` / `split` / `hook_intro`) | ✅ byte-identical | pure, deterministic geometry |
| Ducked background-music graph → `[aout]` | ✅ byte-identical | pure, deterministic |
| libass caption burn, brand watermark (past `[comp]`) | ❌ executor-only | escape an absolute path + embed `utils.font_dir()`, resolved at render time |
| VFX / smart-handling (setpts, blur-pad) / b-roll | ❌ executor-only | probe/param-driven, non-deterministic |

Chroma / PiP diameter / margin / loudnorm targets are always the executor's
shipping defaults (`reelforge.py` never overrides them), so they are baked as
constants that match `_chroma_filter` / `_build_audio_graph` output exactly.

## Spec

```json
{
  "output":  { "width": 1080, "height": 1920, "fps": 30 },
  "layout":  "pip",
  "avatar":  { "input": 1, "diameter": 480, "margin": 48 },
  "caption_ass": "captions.ass",
  "audio":   { "narration": 2, "bgm": 3 }
}
```

`layout` defaults to `captions_only` (no avatar input). The avatar overlays
(`pip` / `split` / `hook_intro`) require an `avatar` input. `audio.bgm` triggers
the ducked-and-loudness-normalised music graph; narration-only emits no audio node
(the executor maps the raw narration input).

## Use

```ts
import { buildFiltergraph, makeSpec } from "@reelforge/render-core";
buildFiltergraph(makeSpec({ layout: "pip", avatarInput: 1, narration: 2, bgm: 3 }));
```

```python
from reelforge_render_core import build_filtergraph, make_spec
build_filtergraph(make_spec(layout="pip", avatar_input=1, narration=2, bgm=3))
```

## Parity

`test/fixtures/golden/filtergraphs.json` pins each spec → filtergraph. The
fixtures **are the executor's real output**; `tests/reelforge/test_render_core_parity.py`
imports `compose_ffmpeg` and asserts the executor's layout / audio builders equal
this library byte-for-byte, so the two can never silently drift.

```bash
# Python library ≡ goldens
PYTHONPATH=python python -m pytest test -q

# TypeScript ≡ goldens (rebuild dist first)
npm run build && npm run test:parity

# Executor ≡ library (run from apps/api, where `app` imports)
python -m pytest ../../tests/reelforge/test_render_core_parity.py -q
```
