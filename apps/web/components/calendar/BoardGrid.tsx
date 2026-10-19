"use client";

import * as React from "react";
import { GripVertical, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  WEEKDAY_LABELS,
  type CalendarDay,
  type CalendarView,
} from "@/components/calendar/calendar-month";
import { entryStatusStyle } from "@/components/calendar/entry-status";
import { entryKey } from "@/components/calendar/use-calendar-board";
import type { BoardEntry } from "@/components/calendar/board-api";

/** MIME type for the drag payload, so foreign drags (files, text) are ignored. */
const DRAG_TYPE = "application/x-menivor-entry";

export interface BoardGridProps {
  view: CalendarView;
  days: readonly CalendarDay[];
  buckets: Map<string, BoardEntry[]>;
  movingKey: string | null;
  onSelect: (entry: BoardEntry) => void;
  onDropOnDay: (key: string, day: Date) => void;
}

const EMPTY: readonly BoardEntry[] = [];

function timeLabel(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function entryTitle(entry: BoardEntry): string {
  const where = entry.channel_label || entry.labels.join(", ") || entry.platforms.join(", ");
  const status = entryStatusStyle(entry.status).label;
  const text = entry.text ? ` - ${entry.text.slice(0, 80)}` : "";
  const hint = entry.can_move ? " (drag to another day, or click to pick a time)" : "";
  return `${status} - ${timeLabel(entry.scheduled_at)} - ${where}${text}${hint}`;
}

function EntryPill({
  entry,
  moving,
  onSelect,
}: Readonly<{ entry: BoardEntry; moving: boolean; onSelect: (e: BoardEntry) => void }>) {
  const style = entryStatusStyle(entry.status);
  const where = entry.channel_label || entry.labels[0] || entry.platforms[0] || "";
  const extra = entry.platforms.length > 1 ? ` +${entry.platforms.length - 1}` : "";
  const label = `${timeLabel(entry.scheduled_at)} ${where}${extra}`.trim();
  const base =
    "flex w-full min-w-0 items-center gap-1 rounded px-1.5 py-0.5 text-left text-[11px] font-medium leading-tight";

  const content = (
    <>
      {entry.can_move && (
        <GripVertical className="size-3 shrink-0 opacity-60" aria-hidden />
      )}
      <span className={cn("size-1.5 shrink-0 rounded-full", style.dot)} aria-hidden />
      <span className="truncate">{label || style.label}</span>
      {moving && <Loader2 className="ml-auto size-3 shrink-0 animate-spin" aria-hidden />}
    </>
  );

  if (!entry.can_move) {
    return (
      <button
        type="button"
        title={entryTitle(entry)}
        onClick={() => onSelect(entry)}
        className={cn(base, style.pill, "cursor-pointer")}
      >
        {content}
      </button>
    );
  }

  return (
    <button
      type="button"
      draggable={!moving}
      title={entryTitle(entry)}
      aria-label={`${entryTitle(entry)}. Press Enter to reschedule.`}
      onClick={() => onSelect(entry)}
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG_TYPE, entryKey(entry));
        e.dataTransfer.effectAllowed = "move";
      }}
      className={cn(
        base,
        style.pill,
        "cursor-grab active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        moving && "opacity-70",
      )}
    >
      {content}
    </button>
  );
}

function DayCell({
  day,
  view,
  entries,
  movingKey,
  onSelect,
  onDropOnDay,
}: Readonly<{
  day: CalendarDay;
  view: CalendarView;
  entries: readonly BoardEntry[];
  movingKey: string | null;
  onSelect: (e: BoardEntry) => void;
  onDropOnDay: (key: string, day: Date) => void;
}>) {
  const [over, setOver] = React.useState(false);
  const isWeek = view === "week";
  const shown = isWeek ? entries : entries.slice(0, 4);
  const overflow = entries.length - shown.length;
  const past = day.date.getTime() + 86_400_000 <= Date.now();

  return (
    <div
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(DRAG_TYPE) || past) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (!over) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const key = e.dataTransfer.getData(DRAG_TYPE);
        if (!key || past) return;
        e.preventDefault();
        onDropOnDay(key, day.date);
      }}
      className={cn(
        "flex flex-col gap-1 border-b border-r border-border p-1.5 transition-colors",
        isWeek ? "min-h-[14rem]" : "min-h-[6.5rem]",
        !day.inCurrentMonth && "bg-muted/30 text-muted-foreground",
        past && "bg-muted/20",
        over && "bg-primary/10 ring-2 ring-inset ring-primary/50",
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          className={cn(
            "inline-flex size-6 items-center justify-center rounded-full text-xs font-medium",
            day.isToday && "bg-primary text-primary-foreground",
          )}
        >
          {day.date.getDate()}
        </span>
        {entries.length > 0 && (
          <span className="text-[10px] tabular-nums text-muted-foreground">{entries.length}</span>
        )}
      </div>
      <div className="flex flex-col gap-1">
        {shown.map((entry) => (
          <EntryPill
            key={entryKey(entry)}
            entry={entry}
            moving={movingKey === entryKey(entry)}
            onSelect={onSelect}
          />
        ))}
        {overflow > 0 && (
          <span className="px-1.5 text-[10px] font-medium text-muted-foreground">
            +{overflow} more (switch to week view)
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * Month/week grid with native HTML5 drag-and-drop: drag a movable entry onto
 * another day to keep its time of day and move its date. Past days do not
 * accept drops. Clicking any entry opens the details / reschedule dialog
 * (the keyboard path for the same move).
 */
export function BoardGrid({
  view,
  days,
  buckets,
  movingKey,
  onSelect,
  onDropOnDay,
}: Readonly<BoardGridProps>) {
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
          <DayCell
            key={day.key}
            day={day}
            view={view}
            entries={buckets.get(day.key) ?? EMPTY}
            movingKey={movingKey}
            onSelect={onSelect}
            onDropOnDay={onDropOnDay}
          />
        ))}
      </div>
    </Card>
  );
}
