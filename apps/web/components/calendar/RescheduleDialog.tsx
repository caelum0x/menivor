"use client";

import * as React from "react";
import { CalendarClock, Film, Loader2, X } from "lucide-react";
import type { CalendarEntry } from "@/lib/calendar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { platformLabel } from "@/components/schedule/platforms";
import {
  isFutureDatetime,
  localDatetimeToUtcISO,
  minScheduleValue,
  toLocalDatetimeValue,
} from "@/components/schedule/platforms";

export interface RescheduleDialogProps {
  /** The entry being rescheduled, or `null` when the dialog is closed. */
  entry: CalendarEntry | null;
  submitting: boolean;
  error: string;
  /** Persist the move; resolves `true` on success (the parent then closes). */
  onSubmit: (scheduledAtISO: string) => Promise<boolean>;
  onClose: () => void;
}

/** A datetime-local value for an ISO instant, or "" when absent/unparseable. */
function toLocalValue(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  return toLocalDatetimeValue(new Date(ms));
}

/**
 * Modal to move a still-`pending` publish to a new time. Pre-fills the entry's
 * current time (rendered in the viewer's local timezone), enforces a future
 * value, and converts back to a UTC instant before calling {@link onSubmit}
 * (PATCH /me/calendar/{id}). Only pending entries ever reach this dialog; the
 * backend still guards the pending-only rule (a lost race surfaces as a 409).
 */
export function RescheduleDialog({
  entry,
  submitting,
  error,
  onSubmit,
  onClose,
}: Readonly<RescheduleDialogProps>) {
  const titleId = React.useId();
  const whenId = React.useId();

  const [when, setWhen] = React.useState<string>("");
  const [localError, setLocalError] = React.useState<string>("");
  const [minWhen, setMinWhen] = React.useState<string>("");

  const entryId = entry?.id ?? null;

  // Re-seed the field whenever a (different) entry opens the dialog.
  React.useEffect(() => {
    if (entry) {
      setWhen(toLocalValue(entry.scheduled_at));
      setLocalError("");
      setMinWhen(minScheduleValue());
    }
    // Only re-run when the opened entry changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryId]);

  const requestClose = React.useCallback(() => {
    if (submitting) return;
    onClose();
  }, [submitting, onClose]);

  React.useEffect(() => {
    if (!entry) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [entry, requestClose]);

  const futureOk = when !== "" && isFutureDatetime(when);
  const canSubmit = futureOk && !submitting;

  const handleSubmit = React.useCallback(async () => {
    setLocalError("");
    const scheduledAt = localDatetimeToUtcISO(when);
    if (!scheduledAt || !isFutureDatetime(when)) {
      setLocalError("Pick a date and time in the future.");
      return;
    }
    const ok = await onSubmit(scheduledAt);
    if (ok) onClose();
  }, [when, onSubmit, onClose]);

  if (!entry) return null;

  const shownError = localError || error;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-black/60"
        onClick={requestClose}
      />

      <div className="relative z-10 flex max-h-[90dvh] w-full max-w-md flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div className="space-y-1">
            <h2
              id={titleId}
              className="flex items-center gap-2 text-lg font-semibold"
            >
              <CalendarClock className="size-5 text-primary" aria-hidden />
              Reschedule publish
            </h2>
            <p className="text-sm text-muted-foreground">
              Move this pending publish to a new time. It stays queued until then.
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={requestClose}
            disabled={submitting}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {entry.job_id && (
              <span className="inline-flex items-center gap-1.5">
                <Film className="size-3.5" aria-hidden />
                <span className="font-mono">{entry.job_id.slice(0, 8)}</span>
              </span>
            )}
            {entry.platforms.length > 0 && (
              <span className="inline-flex flex-wrap items-center gap-1.5">
                {entry.platforms.map((platform) => (
                  <span
                    key={platform}
                    className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-medium"
                  >
                    {platformLabel(platform)}
                  </span>
                ))}
              </span>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor={whenId}>Publish at</Label>
            <Input
              id={whenId}
              type="datetime-local"
              value={when}
              min={minWhen}
              disabled={submitting}
              onChange={(e) => setWhen(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Uses your device timezone. Must be in the future.
            </p>
            {when !== "" && !futureOk && (
              <p className="text-xs text-destructive">
                Choose a time later than now.
              </p>
            )}
          </div>

          {shownError && (
            <p className="text-sm text-destructive">{shownError}</p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-5">
          <Button
            variant="outline"
            onClick={requestClose}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={!canSubmit}>
            {submitting ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <CalendarClock className="size-4" aria-hidden />
            )}
            {submitting ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
