/** Clipfarm Console feature — public surface for routing + reuse. */

export { ClipfarmConsoleScreen } from "./ClipfarmConsoleScreen";
export { TriggerPanel, type TriggerPanelProps } from "./components/TriggerPanel";
export { PacingPanel, type PacingPanelProps } from "./components/PacingPanel";
export {
  RunHistoryCard,
  type RunHistoryCardProps,
} from "./components/RunHistoryCard";
export {
  buildRunInput,
  canTriggerRun,
  formatRunSummary,
  formatScheduleSummary,
  newIdempotencyKey,
  parseCsvList,
  parseSourceLines,
  runOutcome,
  totalRenderedToday,
  DEFAULT_ASPECT,
  PLATFORM_OPTIONS,
  type PlatformOption,
} from "./logic";
