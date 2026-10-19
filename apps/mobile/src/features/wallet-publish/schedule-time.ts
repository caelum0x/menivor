/**
 * Pure helpers for turning a relative "when" choice into the future ISO-8601 UTC
 * timestamp that POST /jobs/{id}/schedule requires. Kept dependency-free so the
 * logic is unit-testable without React Native. Time math only — never money.
 */

export interface ScheduleOffset {
  id: string;
  label: string;
  /** Milliseconds into the future from "now". */
  ms: number;
}

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

/** Selectable publish-time offsets, soonest first. */
export const SCHEDULE_OFFSETS: readonly ScheduleOffset[] = [
  { id: "1h", label: "In 1 hour", ms: HOUR_MS },
  { id: "3h", label: "In 3 hours", ms: 3 * HOUR_MS },
  { id: "24h", label: "In 24 hours", ms: DAY_MS },
  { id: "7d", label: "In 7 days", ms: 7 * DAY_MS },
];

/**
 * Compute the ISO-8601 UTC timestamp `offsetMs` in the future from `now`.
 * The backend requires a strictly-future time; every offset here is positive so
 * the result is always ahead of `now`.
 */
export function scheduledAtFromOffset(
  offsetMs: number,
  now: number = Date.now(),
): string {
  return new Date(now + offsetMs).toISOString();
}

/** Look up an offset preset by id. */
export function findOffset(id: string): ScheduleOffset | undefined {
  return SCHEDULE_OFFSETS.find((offset) => offset.id === id);
}

/**
 * Human-readable local rendering of an ISO timestamp for confirmation UI.
 * Falls back to the raw string if the value can't be parsed.
 */
export function formatLocalTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}
