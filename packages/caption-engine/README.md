# @reelforge/caption-engine

Word-level ASR timestamps → styled **ASS** subtitle string. Shared so the client
renders an exact caption preview and the Python worker (`app/services/captions`)
burns the **byte-identical** ASS.

Pure, deterministic string assembly → the TypeScript and Python ports produce
identical output, verified by golden `.ass` fixtures.

## Presets

`hormozi` (Montserrat Black, ALL CAPS, white + `#FFD93D` highlight, 1–2 words) ·
`karaoke-classic` · `minimal-top-label` (ASMR top label) · `brainrot-popin`.

## Use

```ts
import { buildAss, getPreset } from "@reelforge/caption-engine";
const ass = buildAss(words, getPreset("hormozi")); // full ASS document string
```

```python
from reelforge_caption_engine import build_ass, get_preset
ass = build_ass(words, get_preset("hormozi"))
```

`words` is `[{ text, start, end }]` (WhisperX word timings).

## Parity

`test/fixtures/golden/*.ass` is the byte-exact contract (generated from Python).

```bash
PYTHONPATH=python python -m pytest test -q     # Python reproduces golden
npm run build && npm run test:parity           # compiled TS matches golden
```
