/**
 * Display helpers for experiment rates the platforms may not report.
 *
 * `completion_rate` and `rewatch_rate` are `null` when no connected platform
 * reported them for a post (most organic short-video APIs do not). A null is
 * "not measured", never 0%: showing 0% would claim nobody finished or
 * replayed the reel.
 */

export const NOT_MEASURED = "not measured";

/** Rate in [0, 1] as a percentage, or "not measured" when absent. */
export function formatMeasuredRate(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NOT_MEASURED;
  return `${(value * 100).toFixed(digits)}%`;
}

export function isMeasured(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

/** Hover/aria explanation for an unmeasured rate. */
export const NOT_MEASURED_HINT =
  "The platform did not report this for these posts, so it is not counted in the ranking.";
