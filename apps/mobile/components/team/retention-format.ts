/**
 * Pure, dependency-free helpers for the workspace data-retention editor:
 * formatting a retention window / timestamp for display and validating the
 * free-text "days" input before it becomes a `PUT` body. These never touch the
 * network and never mutate their inputs — they only shape what the editor shows
 * and gate what it will submit.
 */

/** The largest retention window the editor accepts (~27 years); guards typos. */
export const MAX_RETENTION_DAYS = 10000;

/** Human-readable label for a retention window (`null` = keep forever). */
export function formatWindow(days: number | null): string {
  if (days === null) return "Keep forever";
  if (days === 0) return "Delete immediately (0 days)";
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** Render an ISO-8601 timestamp as a short local date-time, or a dash. */
export function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString();
}

/** The seed text for a numeric input given a window (`null` -> empty string). */
export function daysToInput(days: number | null): string {
  return days === null ? "" : String(days);
}

/** Result of validating a single free-text "days" input. */
export interface DaysInputResult {
  /** The parsed non-negative integer, or `null` for keep-forever / empty. */
  value: number | null;
  /** A user-facing validation message, or `null` when the input is valid. */
  error: string | null;
}

/**
 * Validate a free-text retention-days input. An empty / whitespace value is a
 * valid keep-forever (`null`). Otherwise it must be a non-negative WHOLE number
 * no greater than {@link MAX_RETENTION_DAYS}; anything else yields an `error`.
 */
export function parseDaysInput(text: string): DaysInputResult {
  const trimmed = text.trim();
  if (trimmed.length === 0) return { value: null, error: null };
  if (!/^\d+$/.test(trimmed)) {
    return { value: null, error: "Enter a whole number of days, or leave blank." };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { value: null, error: "Enter a whole number of days, or leave blank." };
  }
  if (value > MAX_RETENTION_DAYS) {
    return {
      value: null,
      error: `Must be ${MAX_RETENTION_DAYS} days or fewer.`,
    };
  }
  return { value, error: null };
}
