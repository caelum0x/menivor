"use client";

import * as React from "react";
import { isCancelableSchedule } from "@/lib/types";
import type { CalendarEntry } from "@/lib/calendar";
import { cn } from "@/lib/utils";
import { entryStatusStyle } from "@/components/calendar/entry-status";
import { platformLabel } from "@/components/schedule/platforms";

export interface CalendarEntryPillProps {
  entry: CalendarEntry;
  /** Fired when a still-pending entry is clicked (opens the reschedule control). */
  onSelect: (entry: CalendarEntry) => void;
}

/** Short local time label (e.g. "9:30 AM") for an ISO instant. */
function formatTime(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * A single entry inside a day cell: a small colour-coded pill showing the local
 * publish time and its first target platform. A still-`pending` entry is a
 * button that opens the reschedule control; anything already run (or otherwise
 * non-pending) renders as static, non-interactive text.
 */
export function CalendarEntryPill({
  entry,
  onSelect,
}: Readonly<CalendarEntryPillProps>) {
  const style = entryStatusStyle(entry.status);
  const time = formatTime(entry.scheduled_at);
  const reschedulable = isCancelableSchedule(entry.status);
  const firstPlatform = entry.platforms[0];
  const platform = firstPlatform ? platformLabel(firstPlatform) : "";
  const extra =
    entry.platforms.length > 1 ? ` +${entry.platforms.length - 1}` : "";
  const label = [time, platform && `· ${platform}${extra}`]
    .filter(Boolean)
    .join(" ");
  const title = `${style.label}${time ? ` — ${time}` : ""}${
    platform ? ` · ${entry.platforms.map(platformLabel).join(", ")}` : ""
  }`;

  const content = (
    <span className="flex min-w-0 items-center gap-1.5">
      <span className={cn("size-1.5 shrink-0 rounded-full", style.dot)} aria-hidden />
      <span className="truncate">{label || style.label}</span>
    </span>
  );

  const base =
    "block w-full rounded px-1.5 py-0.5 text-left text-[11px] font-medium leading-tight";

  if (reschedulable) {
    return (
      <button
        type="button"
        title={`${title} — click to reschedule`}
        onClick={() => onSelect(entry)}
        className={cn(
          base,
          style.pill,
          "cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        {content}
      </button>
    );
  }

  return (
    <span title={title} className={cn(base, style.pill, "cursor-default")}>
      {content}
    </span>
  );
}
