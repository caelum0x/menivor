/**
 * Status → presentation mapping for calendar entry pills. Colours are drawn from
 * the shared theme tokens (same palette as the scheduled-publishes list) so the
 * calendar reads consistently across light/dark modes.
 */

import type { ScheduledPublishStatus } from "@/lib/types";

export interface EntryStatusStyle {
  label: string;
  /** Tailwind classes for the pill background + text. */
  pill: string;
  /** A small left-edge accent used on the day cell / pill. */
  dot: string;
}

const STYLES: Record<string, EntryStatusStyle> = {
  pending: {
    label: "Pending",
    pill: "bg-primary/15 text-primary hover:bg-primary/25",
    dot: "bg-primary",
  },
  queued: {
    label: "Queued",
    pill: "bg-primary/15 text-primary hover:bg-primary/25",
    dot: "bg-primary",
  },
  publishing: {
    label: "Publishing",
    pill: "bg-accent/15 text-accent",
    dot: "bg-accent",
  },
  published: {
    label: "Published",
    pill: "bg-success/15 text-success",
    dot: "bg-success",
  },
  failed: {
    label: "Failed",
    pill: "bg-destructive/15 text-destructive",
    dot: "bg-destructive",
  },
  scheduled: {
    label: "Scheduled",
    pill: "bg-primary/15 text-primary hover:bg-primary/25",
    dot: "bg-primary",
  },
  processing: {
    label: "Processing",
    pill: "bg-accent/15 text-accent",
    dot: "bg-accent",
  },
  held: {
    label: "Held for review",
    pill: "bg-destructive/10 text-destructive",
    dot: "bg-destructive",
  },
  canceled: {
    label: "Canceled",
    pill: "bg-secondary text-muted-foreground line-through",
    dot: "bg-muted-foreground",
  },
};

const FALLBACK: EntryStatusStyle = {
  label: "Scheduled",
  pill: "bg-secondary text-secondary-foreground",
  dot: "bg-muted-foreground",
};

/** Presentation for a schedule status, falling back for unknown values. */
export function entryStatusStyle(
  status: ScheduledPublishStatus,
): EntryStatusStyle {
  return STYLES[status as string] ?? FALLBACK;
}
