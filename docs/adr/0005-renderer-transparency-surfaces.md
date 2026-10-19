# ADR 0005 — Surface the shared golden-parity packages as client labs

**Status:** accepted

## Context
Five shared-logic packages already own the numbers the pipeline renders with —
`shot-template-schema` (shot structures), `caption-engine` (ASS caption styles),
`render-core` (the `RenderSpec → -filter_complex` builder), and `growth-analytics`
(hook gate, retention/reach, A/B winner). Under [ADR 0004](0004-shared-package-parity.md)
each is byte/bit-identical to its Python port. But those registries were only ever
*consumed internally* by the renderer — a creator could not see the hook gate a
reel must clear, the caption look before rendering, or the exact filtergraph the
worker runs. The logic was trustworthy but invisible.

## Decision
Expose each shared package as a **read-only client "lab"** that imports the real
package (never a reimplementation) and renders its output live. The lab is the
same on web and mobile because the package is the same:

| Package | Web route | Mobile screen |
|---|---|---|
| `shot-template-schema` | `/blueprints` | — |
| `caption-engine` | `/captions` | — |
| `render-core` | `/filtergraph` | — |
| `growth-analytics` (hook) | `/hook-lab` | `hook-lab` |
| `growth-analytics` (retention) | `/retention-lab` | `retention-lab` |
| `growth-analytics` (ab) | `/ab-lab` | `ab-lab` |

Rules the labs follow:
- **Real logic only.** Scores/graphs/tiers come from the package's exported
  functions (`hookScore`, `buildFiltergraph`, `reachTier`, `selectWinner`, …),
  never recomputed in the view. Only *visualization* constants (e.g. the private
  `WEIGHTS` used to draw a contribution bar) may be mirrored, and are commented as such.
- **No fabricated data.** Inputs are user-entered (a curve to analyze, signals to
  tune) or the package's own static registries (presets). Nothing is invented to
  fill a chart.
- **ui-kit domain components.** `HookScoreGauge`, `SegmentSlotBar`,
  `RetentionCurveChart`, `StatTile` render the package output, so the same
  component draws the same number on both surfaces.
- **Mobile consumes the package the same way as `api-contract`** — a `file:`
  dependency plus a `node_modules/@reelforge/*` symlink, so Metro and `tsc`
  resolve the built `dist`.

## Consequences
- "What you see = what the renderer runs": the shot structure, caption style,
  filtergraph, hook gate, reach tier, and A/B winner a creator inspects are the
  exact values the pipeline composes/scores with — no drift possible, because
  there is one implementation.
- The labs are pure client-side and stateless; they add no backend surface and
  need no auth (they operate on the caller's own inputs).
- Adding a shared package to a new surface is a wiring step (tsconfig path on web,
  `file:` dep + symlink on mobile), not a re-implementation.
