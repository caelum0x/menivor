/**
 * `@reelforge/growth-analytics` — pure funnel / retention / hook / A-B utilities.
 *
 * Takes data, returns verdicts (no I/O), bit-identical to the Python port
 * (`reelforge_growth_analytics`, golden fixtures) so web/mobile/api compute the
 * same numbers.
 */

export { clamp01, round6 } from "./util.js";
export {
  normalizeCurve,
  reachTier,
  dropoff,
  type ReachTier,
  type Dropoff,
} from "./retention.js";
export {
  hookScore,
  GATE,
  type HookSignals,
  type HookResult,
} from "./hook.js";
export {
  selectWinner,
  type Variant,
  type WinnerResult,
} from "./ab.js";
