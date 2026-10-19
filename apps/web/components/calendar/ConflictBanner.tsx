"use client";

import * as React from "react";
import { AlertTriangle, Info, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MoveConflict, MoveNotice } from "@/components/calendar/use-calendar-board";

function localLabel(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  return new Date(ms).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Inline result of a drag that the posting policy refused: the entry already
 * snapped back; offer the next legal slot or keeping the chosen one anyway.
 */
export function ConflictBanner({
  conflict,
  busy,
  onUseSuggested,
  onKeepAnyway,
  onDismiss,
}: Readonly<{
  conflict: MoveConflict;
  busy: boolean;
  onUseSuggested: (iso: string) => void;
  onKeepAnyway: () => void;
  onDismiss: () => void;
}>) {
  const suggested = conflict.check.suggested_at;
  return (
    <div
      role="alert"
      className="mb-4 flex flex-col gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
        <div className="space-y-1 text-sm">
          <p className="font-medium">
            Moved back: {localLabel(conflict.attemptedISO)} is outside the posting rules.
          </p>
          <p className="text-muted-foreground">{conflict.check.reason}</p>
          {suggested && (
            <p className="text-muted-foreground">
              Next open slot: <span className="font-medium text-foreground">{localLabel(suggested)}</span>
            </p>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        {suggested && (
          <Button size="sm" disabled={busy} onClick={() => onUseSuggested(suggested)}>
            Use suggested time
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={busy} onClick={onKeepAnyway}>
          Keep my time
        </Button>
        <Button size="icon" variant="ghost" aria-label="Dismiss" onClick={onDismiss}>
          <X className="size-4" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

export function NoticeBanner({
  notice,
  onDismiss,
}: Readonly<{ notice: MoveNotice; onDismiss: () => void }>) {
  const isError = notice.tone === "error";
  const Icon = isError ? AlertTriangle : Info;
  return (
    <div
      role={isError ? "alert" : "status"}
      className={
        isError
          ? "mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
          : "mb-4 flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm"
      }
    >
      <span className="flex items-center gap-2">
        <Icon className={isError ? "size-4 text-destructive" : "size-4 text-muted-foreground"} aria-hidden />
        {notice.message}
      </span>
      <Button size="icon" variant="ghost" aria-label="Dismiss" onClick={onDismiss}>
        <X className="size-4" aria-hidden />
      </Button>
    </div>
  );
}

/** Local clock labels (e.g. "1 PM") for UTC best-hours, per platform label. */
export function bestTimesLocal(
  bestHoursUtc: Record<string, number[]>,
  platforms: readonly string[],
): { platform: string; times: string[] }[] {
  return platforms
    .filter((p) => (bestHoursUtc[p] ?? []).length > 0)
    .map((p) => ({
      platform: p,
      times: (bestHoursUtc[p] ?? []).map((hour) => {
        const d = new Date();
        d.setUTCHours(hour, 0, 0, 0);
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      }),
    }));
}
