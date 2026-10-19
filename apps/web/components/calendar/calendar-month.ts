/**
 * Pure, timezone-local date math for the publishing calendar grid.
 *
 * All API `scheduled_at` values are UTC ISO-8601 instants; every helper here
 * works in the VIEWER's local timezone so entries land on the day the creator
 * actually sees them. No mutation: every function returns fresh values.
 */

import type { CalendarEntry } from "@/lib/calendar";

export type CalendarView = "month" | "week";

/** A single rendered day cell in the grid. */
export interface CalendarDay {
  /** Local midnight of the day. */
  date: Date;
  /** Stable `YYYY-MM-DD` key in local time. */
  key: string;
  /** Whether the day belongs to the reference month (dimmed otherwise). */
  inCurrentMonth: boolean;
  /** Whether the day is today (in local time). */
  isToday: boolean;
}

/** Sunday-first weekday header labels. */
export const WEEKDAY_LABELS = [
  "Sun",
  "Mon",
  "Tue",
  "Wed",
  "Thu",
  "Fri",
  "Sat",
] as const;

const MS_PER_DAY = 86_400_000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Local midnight of a date's day. */
export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** A new date `days` days after `date` (local calendar arithmetic). */
export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** A new date `months` months after `date`, clamped to a valid day-of-month. */
export function addMonths(date: Date, months: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + months, 1);
}

/** Stable `YYYY-MM-DD` key for a date in local time. */
export function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function isSameLocalDay(a: Date, b: Date): boolean {
  return localDayKey(a) === localDayKey(b);
}

/** The Sunday on or before `date` (start of that calendar week). */
function startOfWeek(date: Date): Date {
  const day = startOfDay(date);
  return addDays(day, -day.getDay());
}

/**
 * Build the day cells for a MONTH grid: whole weeks (Sunday-first) covering the
 * reference month, so leading/trailing days spill from the adjacent months.
 */
export function buildMonthDays(ref: Date, now: Date = new Date()): CalendarDay[] {
  const firstOfMonth = new Date(ref.getFullYear(), ref.getMonth(), 1);
  const gridStart = startOfWeek(firstOfMonth);
  const daysInMonth = new Date(
    ref.getFullYear(),
    ref.getMonth() + 1,
    0,
  ).getDate();
  const leading = firstOfMonth.getDay();
  const weeks = Math.ceil((leading + daysInMonth) / 7);

  const days: CalendarDay[] = [];
  for (let i = 0; i < weeks * 7; i += 1) {
    const date = addDays(gridStart, i);
    days.push({
      date,
      key: localDayKey(date),
      inCurrentMonth: date.getMonth() === ref.getMonth(),
      isToday: isSameLocalDay(date, now),
    });
  }
  return days;
}

/** Build the seven day cells for a WEEK grid containing the reference date. */
export function buildWeekDays(ref: Date, now: Date = new Date()): CalendarDay[] {
  const gridStart = startOfWeek(ref);
  const days: CalendarDay[] = [];
  for (let i = 0; i < 7; i += 1) {
    const date = addDays(gridStart, i);
    days.push({
      date,
      key: localDayKey(date),
      inCurrentMonth: true,
      isToday: isSameLocalDay(date, now),
    });
  }
  return days;
}

/** The day cells for a view (month or week) around the reference date. */
export function buildDays(
  view: CalendarView,
  ref: Date,
  now: Date = new Date(),
): CalendarDay[] {
  return view === "month" ? buildMonthDays(ref, now) : buildWeekDays(ref, now);
}

/**
 * The inclusive `[startISO, endISO]` UTC window covering a view's day cells —
 * from the first cell's local midnight to the last cell's local end-of-day. Sent
 * as the `start` / `end` query params to `GET /me/calendar` (the backend clamps
 * an over-wide window; a month grid is ~42 days, well under the ~92-day cap).
 */
export function rangeForView(
  view: CalendarView,
  ref: Date,
  now: Date = new Date(),
): { startISO: string; endISO: string } {
  const days = buildDays(view, ref, now);
  const first = days[0];
  const last = days[days.length - 1];
  if (!first || !last) {
    const nowIso = new Date(now.getTime()).toISOString();
    return { startISO: nowIso, endISO: nowIso };
  }
  const start = new Date(first.date.getTime());
  const end = new Date(last.date.getTime() + MS_PER_DAY - 1);
  return { startISO: start.toISOString(), endISO: end.toISOString() };
}

/**
 * Group entries into local-day buckets, sorted chronologically within each day.
 * Entries with no (or an unparseable) `scheduled_at` are skipped.
 */
export function bucketEntriesByDay<
  T extends { scheduled_at: string | null } = CalendarEntry,
>(entries: readonly T[]): Map<string, T[]> {
  const buckets = new Map<string, T[]>();
  for (const entry of entries) {
    if (!entry.scheduled_at) continue;
    const ms = new Date(entry.scheduled_at).getTime();
    if (Number.isNaN(ms)) continue;
    const key = localDayKey(new Date(ms));
    const list = buckets.get(key);
    if (list) list.push(entry);
    else buckets.set(key, [entry]);
  }
  for (const list of buckets.values()) {
    list.sort((a, b) => {
      const at = a.scheduled_at ? new Date(a.scheduled_at).getTime() : 0;
      const bt = b.scheduled_at ? new Date(b.scheduled_at).getTime() : 0;
      return at - bt;
    });
  }
  return buckets;
}

/** Human label for the current view (e.g. "September 2026" or a week range). */
export function viewLabel(view: CalendarView, ref: Date): string {
  if (view === "month") {
    return ref.toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
    });
  }
  const days = buildWeekDays(ref);
  const first = days[0]?.date ?? startOfDay(ref);
  const last = days[days.length - 1]?.date ?? first;
  const sameMonth = first.getMonth() === last.getMonth();
  const firstLabel = first.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const lastLabel = last.toLocaleDateString(undefined, {
    month: sameMonth ? undefined : "short",
    day: "numeric",
    year: "numeric",
  });
  return `${firstLabel} – ${lastLabel}`;
}

/** Shift the reference date one step forward/backward for the given view. */
export function shiftRef(
  view: CalendarView,
  ref: Date,
  direction: 1 | -1,
): Date {
  return view === "month"
    ? addMonths(ref, direction)
    : addDays(ref, direction * 7);
}
