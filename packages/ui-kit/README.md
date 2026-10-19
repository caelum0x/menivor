# @reelforge/ui-kit

Shared **React components + design tokens** for the ReelForge web/Electron
surfaces, plus a **framework-free `tokens.json`** that `apps/mobile` and the
Rust/GPUI desktop re-map — so all four apps share **one palette / scale** even
where components can't be shared.

## What's in it

- **Tokens** (`colors`, `spacing`, `radii`, `fontSizes`/`fontWeights`, `zIndex`,
  `platformColors`) — the canonical palette (matches the mobile theme). Emitted
  to `src/tokens/tokens.json` by `npm run build` for non-React consumers.
- **Format** — pure `formatUsdMicros` / `formatCredits` / `formatDuration` /
  `formatPercent` / `formatCompact`, so numbers render identically everywhere.
- **Primitives** — `Button` · `Card` · `Badge`.
- **Domain** (reuse the shared packages so metrics match the backend) —
  `MoneyText`, `PlatformIcon`, `HookScoreGauge` (uses `@reelforge/growth-analytics`).
- **Hooks** — `useDebounce`.

```ts
import { Button, HookScoreGauge, formatUsdMicros, colors } from "@reelforge/ui-kit";
```

```jsonc
// mobile / desktop re-map the framework-free export
import tokens from "@reelforge/ui-kit/tokens.json";
```

> Native `apps/desktop` (Rust/GPUI) consumes only `tokens.json` (built into a Rust
> theme module); it can't import React components. `apps/web` + Electron are the
> full React consumers.

## Build

```bash
npm run build   # tsc → dist + emits src/tokens/tokens.json (the source of truth)
```
