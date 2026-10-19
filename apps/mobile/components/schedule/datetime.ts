/**
 * Pure date/time helpers for the "simple input" scheduler picker (used when
 * `@react-native-community/datetimepicker` is not installed). The user edits a
 * calendar date + wall-clock time in their DEVICE-LOCAL timezone; these helpers
 * combine that into a real `Date` and serialise it to the ISO-8601 UTC string
 * the backend requires (it validates `scheduled_at` is a future UTC instant).
 *
 * All functions are pure and side-effect free so they are trivially testable.
 */

/** Two-digit zero-padded string for a small non-negative integer. */
function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** `Date` -> local calendar-date field value ("YYYY-MM-DD"). */
export function toDateField(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(
    date.getDate(),
  )}`;
}

/** `Date` -> local wall-clock time field value ("HH:MM"). */
export function toTimeField(date: Date): string {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/**
 * Combine a local "YYYY-MM-DD" date and "HH:MM" time into a `Date`, or `null`
 * when either field is blank, malformed, or out of range. Strict parsing (no
 * `Date`-string coercion) keeps untrusted input from silently rolling over
 * (e.g. month 13 -> next year).
 */
export function combineLocalDateTime(
  dateField: string,
  timeField: string,
): Date | null {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec((dateField || "").trim());
  const timeMatch = /^(\d{1,2}):(\d{2})$/.exec((timeField || "").trim());
  if (!dateMatch || !timeMatch) return null;

  const year = Number(dateMatch[1]);
  const month = Number(dateMatch[2]);
  const day = Number(dateMatch[3]);
  const hours = Number(timeMatch[1]);
  const minutes = Number(timeMatch[2]);

  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  if (hours > 23 || minutes > 59) return null;

  const date = new Date(year, month - 1, day, hours, minutes, 0, 0);
  // Reject rollovers (e.g. 2026-02-31 -> March): the constructed fields must
  // round-trip exactly.
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day ||
    date.getHours() !== hours ||
    date.getMinutes() !== minutes
  ) {
    return null;
  }
  return date;
}

/** `Date` -> ISO-8601 UTC string (with the trailing `Z`) for the API. */
export function toIsoUtc(date: Date): string {
  return date.toISOString();
}

/**
 * A friendly local-time label for previewing the chosen instant, e.g.
 * "Mon, Aug 11, 2026, 2:30 PM". Falls back to a plain ISO-ish string if the
 * platform's `Intl`/`toLocaleString` is unavailable.
 */
export function formatLocal(date: Date): string {
  try {
    return date.toLocaleString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return `${toDateField(date)} ${toTimeField(date)}`;
  }
}

/**
 * A sensible default schedule instant: `minutesAhead` from `from` (default one
 * hour from now), rounded UP to the next 5-minute mark and zeroed seconds — so
 * the pre-filled fields are always comfortably in the future.
 */
export function defaultScheduleAt(
  from: Date = new Date(),
  minutesAhead = 60,
): Date {
  const base = new Date(from.getTime() + minutesAhead * 60_000);
  base.setSeconds(0, 0);
  const remainder = base.getMinutes() % 5;
  if (remainder !== 0) {
    base.setMinutes(base.getMinutes() + (5 - remainder));
  }
  return base;
}
