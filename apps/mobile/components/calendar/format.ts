/**
 * Pure presentation helpers for the publishing-calendar agenda. Groups the
 * caller's calendar entries into per-day sections (in the DEVICE-LOCAL timezone,
 * even though the API speaks UTC) and formats the day/time labels. Reuses the
 * shared schedule badges + platform labels so the calendar never drifts from the
 * Scheduled screen. All functions are pure and side-effect free.
 */

import { statusBadge, type ScheduleBadge } from "@/components/schedule/format";
import { platformLabel } from "@/components/schedule/platforms";
import type { CalendarEntry } from "@/lib/calendar";

export type { ScheduleBadge };
export { statusBadge };

/** One day's worth of entries for a `SectionList` (agenda view). */
export interface DaySection {
  /** Stable local calendar-day key ("YYYY-MM-DD") for `keyExtractor`. */
  key: string;
  /** Friendly day header, e.g. "Today · Thu, Aug 13". */
  title: string;
  /** The day's entries, soonest-first. */
  data: CalendarEntry[];
}

/** Two-digit zero-padded string for a small non-negative integer. */
function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** `Date` -> local calendar-day key ("YYYY-MM-DD"). */
function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(
    date.getDate(),
  )}`;
}

/** True when `date` is the same local calendar day as `ref`. */
function isSameLocalDay(date: Date, ref: Date): boolean {
  return localDayKey(date) === localDayKey(ref);
}

/**
 * True only for a still-reschedulable / cancelable entry. `pending` is the one
 * lifecycle state the owner may move or cancel.
 */
export function isPending(entry: CalendarEntry): boolean {
  return entry.status === "pending";
}

/** Comma-joined human labels for an entry's target platforms. */
export function platformSummary(entry: CalendarEntry): string {
  const list = entry.platforms ?? [];
  if (list.length === 0) return "No platforms";
  return list.map(platformLabel).join(", ");
}

/**
 * A friendly local wall-clock label for an entry, e.g. "2:30 PM". Falls back to
 * the raw ISO value (or a placeholder) when it is missing/unparseable so the UI
 * never blanks.
 */
export function formatEntryTime(iso: string | null): string {
  if (!iso) return "Time not set";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  try {
    return date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/** A friendly day-header label for a local calendar day relative to `now`. */
function dayTitle(date: Date, now: Date): string {
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);

  let prefix = "";
  if (isSameLocalDay(date, now)) prefix = "Today · ";
  else if (isSameLocalDay(date, tomorrow)) prefix = "Tomorrow · ";
  else if (isSameLocalDay(date, yesterday)) prefix = "Yesterday · ";

  let label: string;
  try {
    label = date.toLocaleDateString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
  } catch {
    label = localDayKey(date);
  }
  return `${prefix}${label}`;
}

/**
 * Group calendar entries into per-day sections in the DEVICE-LOCAL timezone,
 * sorted chronologically (days ascending, entries within a day soonest-first).
 * Entries with a missing/unparseable time are bucketed last under an "Unscheduled"
 * section so nothing is silently dropped.
 */
export function groupByDay(
  entries: readonly CalendarEntry[],
  now: Date = new Date(),
): DaySection[] {
  const buckets = new Map<string, { date: Date | null; rows: CalendarEntry[] }>();

  for (const entry of entries) {
    const parsed = entry.scheduled_at ? new Date(entry.scheduled_at) : null;
    const valid = parsed !== null && !Number.isNaN(parsed.getTime());
    const key = valid ? localDayKey(parsed as Date) : "unscheduled";
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.rows.push(entry);
    } else {
      buckets.set(key, { date: valid ? (parsed as Date) : null, rows: [entry] });
    }
  }

  const timeOf = (entry: CalendarEntry): number => {
    if (!entry.scheduled_at) return Number.POSITIVE_INFINITY;
    const t = new Date(entry.scheduled_at).getTime();
    return Number.isNaN(t) ? Number.POSITIVE_INFINITY : t;
  };

  return Array.from(buckets.entries())
    .sort(([a], [b]) => {
      // The "unscheduled" bucket always sorts last.
      if (a === "unscheduled") return 1;
      if (b === "unscheduled") return -1;
      return a < b ? -1 : a > b ? 1 : 0;
    })
    .map(([key, { date, rows }]) => ({
      key,
      title: date ? dayTitle(date, now) : "Unscheduled",
      data: [...rows].sort((x, y) => timeOf(x) - timeOf(y)),
    }));
}
