"use client";

import * as React from "react";
import type { CalendarEntry } from "@/lib/calendar";
import { cn } from "@/lib/utils";
import type { CalendarDay, CalendarView } from "@/components/calendar/calendar-month";
import { CalendarEntryPill } from "@/components/calendar/CalendarEntryPill";

export interface CalendarDayCellProps {
  day: CalendarDay;
  view: CalendarView;
  entries: readonly CalendarEntry[];
  onSelect: (entry: CalendarEntry) => void;
}

/**
 * One day cell in the grid: the day number (today highlighted, out-of-month days
 * dimmed in the month view) plus the day's colour-coded entry pills. In the week
 * view cells are taller so every entry is shown; in the month view a tall day is
 * capped with a "+N more" hint to keep the grid compact.
 */
export function CalendarDayCell({
  day,
  view,
  entries,
  onSelect,
}: Readonly<CalendarDayCellProps>) {
  const isWeek = view === "week";
  const cap = isWeek ? entries.length : 3;
  const shown = entries.slice(0, cap);
  const overflow = entries.length - shown.length;

  return (
    <div
      className={cn(
        "flex flex-col gap-1 border-b border-r border-border p-1.5",
        isWeek ? "min-h-[14rem]" : "min-h-[6.5rem]",
        !day.inCurrentMonth && "bg-muted/30 text-muted-foreground",
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          className={cn(
            "inline-flex size-6 items-center justify-center rounded-full text-xs font-medium",
            day.isToday && "bg-primary text-primary-foreground",
            !day.isToday && !day.inCurrentMonth && "text-muted-foreground",
          )}
        >
          {day.date.getDate()}
        </span>
        {entries.length > 0 && (
          <span className="text-[10px] tabular-nums text-muted-foreground">
            {entries.length}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        {shown.map((entry) => (
          <CalendarEntryPill key={entry.id} entry={entry} onSelect={onSelect} />
        ))}
        {overflow > 0 && (
          <span className="px-1.5 text-[10px] font-medium text-muted-foreground">
            +{overflow} more
          </span>
        )}
      </div>
    </div>
  );
}
