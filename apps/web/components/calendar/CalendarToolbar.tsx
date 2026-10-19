"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  viewLabel,
  type CalendarView,
} from "@/components/calendar/calendar-month";

export interface CalendarToolbarProps {
  view: CalendarView;
  ref: Date;
  loading: boolean;
  onViewChange: (view: CalendarView) => void;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  onRefresh: () => void;
}

const VIEWS: readonly { id: CalendarView; label: string }[] = [
  { id: "month", label: "Month" },
  { id: "week", label: "Week" },
];

/**
 * Calendar controls: month/week toggle, previous/next/today navigation, the
 * current period label, and a refresh button. Purely presentational; all state
 * lives in {@link useCalendar}.
 */
export function CalendarToolbar({
  view,
  ref,
  loading,
  onViewChange,
  onPrev,
  onNext,
  onToday,
  onRefresh,
}: Readonly<CalendarToolbarProps>) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <div className="flex items-center rounded-md border border-input p-0.5">
          <Button
            variant="ghost"
            size="sm"
            className="size-8 p-0"
            aria-label="Previous"
            onClick={onPrev}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="size-8 p-0"
            aria-label="Next"
            onClick={onNext}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
        </div>
        <Button variant="outline" size="sm" onClick={onToday}>
          Today
        </Button>
        {/* Locale-formatted on both server and browser; the visitor's locale wins. */}
        <span className="ml-1 text-lg font-semibold tracking-tight" suppressHydrationWarning>
          {viewLabel(view, ref)}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <div className="flex items-center rounded-md border border-input p-0.5">
          {VIEWS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => onViewChange(option.id)}
              aria-pressed={view === option.id}
              className={cn(
                "rounded px-3 py-1 text-sm font-medium transition-colors",
                view === option.id
                  ? "bg-secondary text-secondary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw
            className={loading ? "size-4 animate-spin" : "size-4"}
            aria-hidden
          />
          Refresh
        </Button>
      </div>
    </div>
  );
}
