"use client";

import * as React from "react";
import type { CalendarEntry } from "@/lib/calendar";
import { Card } from "@/components/ui/card";
import {
  WEEKDAY_LABELS,
  type CalendarDay,
  type CalendarView,
} from "@/components/calendar/calendar-month";
import { CalendarDayCell } from "@/components/calendar/CalendarDayCell";

export interface CalendarGridProps {
  view: CalendarView;
  days: readonly CalendarDay[];
  buckets: Map<string, CalendarEntry[]>;
  onSelect: (entry: CalendarEntry) => void;
}

const EMPTY: readonly CalendarEntry[] = [];

/**
 * The month/week grid: a Sunday-first weekday header over a 7-column grid of
 * {@link CalendarDayCell}s. Presentational only — day cells and entry buckets
 * are computed upstream by {@link useCalendar}.
 */
export function CalendarGrid({
  view,
  days,
  buckets,
  onSelect,
}: Readonly<CalendarGridProps>) {
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-cols-7 border-b border-border bg-muted/40">
        {WEEKDAY_LABELS.map((label) => (
          <div
            key={label}
            className="border-r border-border px-2 py-2 text-center text-xs font-medium uppercase tracking-wide text-muted-foreground last:border-r-0"
          >
            {label}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 [&>*:nth-child(7n)]:border-r-0">
        {days.map((day) => (
          <CalendarDayCell
            key={day.key}
            day={day}
            view={view}
            entries={buckets.get(day.key) ?? EMPTY}
            onSelect={onSelect}
          />
        ))}
      </div>
    </Card>
  );
}
