"use client";

import * as React from "react";
import { CalendarClock, CheckCircle2, ExternalLink, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  isFutureDatetime,
  localDatetimeToUtcISO,
  minScheduleValue,
  toLocalDatetimeValue,
} from "@/components/schedule/platforms";
import { useApiToken } from "@/lib/use-api-token";
import { entryStatusStyle } from "@/components/calendar/entry-status";
import { bestTimesLocal } from "@/components/calendar/ConflictBanner";
import {
  checkSlot,
  errorMessage,
  type BoardEntry,
  type SlotCheck,
} from "@/components/calendar/board-api";
import { safeServerText } from "@/src/shared/errors/friendly";

function toLocalValue(iso: string | null): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? "" : toLocalDatetimeValue(new Date(ms));
}

/**
 * Details for any calendar entry and, when it has not started yet, a
 * date-time picker that checks the posting policy live before saving (the
 * keyboard-accessible path for the same move as drag-and-drop).
 */
export function EntryDialog({
  entry,
  bestHours,
  busy,
  onMove,
  onClose,
}: Readonly<{
  entry: BoardEntry | null;
  bestHours: Record<string, number[]>;
  busy: boolean;
  onMove: (entry: BoardEntry, iso: string, force: boolean) => Promise<boolean>;
  onClose: () => void;
}>) {
  const getApiToken = useApiToken();
  const titleId = React.useId();
  const whenId = React.useId();
  const [when, setWhen] = React.useState("");
  const [check, setCheck] = React.useState<SlotCheck | null>(null);
  const [checking, setChecking] = React.useState(false);
  const [checkError, setCheckError] = React.useState("");

  const key = entry ? `${entry.source}:${entry.id}` : "";
  React.useEffect(() => {
    if (entry) {
      setWhen(toLocalValue(entry.scheduled_at));
      setCheck(null);
      setCheckError("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Live policy check (debounced) whenever the picked time changes.
  React.useEffect(() => {
    if (!entry || !entry.can_move) return;
    const iso = localDatetimeToUtcISO(when);
    if (!iso || !isFutureDatetime(when) || iso === entry.scheduled_at) {
      setCheck(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setChecking(true);
      setCheckError("");
      try {
        const token = await getApiToken();
        const result = await checkSlot(entry, iso, { token });
        if (!cancelled) setCheck(result);
      } catch (err) {
        if (!cancelled) setCheckError(errorMessage(err, "Couldn't check this slot."));
      } finally {
        if (!cancelled) setChecking(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [entry, when, getApiToken]);

  React.useEffect(() => {
    if (!entry) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [entry, busy, onClose]);

  if (!entry) return null;

  const style = entryStatusStyle(entry.status);
  const iso = localDatetimeToUtcISO(when);
  const futureOk = when !== "" && isFutureDatetime(when);
  const hints = bestTimesLocal(bestHours, entry.platforms);
  const blocked = check !== null && !check.allow;

  const save = async (force: boolean) => {
    if (!iso) return;
    const ok = await onMove(entry, iso, force);
    if (ok) onClose();
  };

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
        onClick={() => !busy && onClose()}
      />
      <div className="relative z-10 flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <div className="space-y-1">
            <h2 id={titleId} className="flex items-center gap-2 text-lg font-semibold">
              <CalendarClock className="size-5 text-primary" aria-hidden />
              {entry.channel_label || entry.labels.join(", ") || "Scheduled post"}
            </h2>
            <p className="text-sm text-muted-foreground">
              {style.label}
              {entry.scheduled_at ? ` - ${new Date(entry.scheduled_at).toLocaleString()}` : ""}
            </p>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose} disabled={busy}>
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
          {entry.text && (
            <p className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3">{entry.text}</p>
          )}
          {entry.error && <p className="text-destructive">{safeServerText(entry.error, "This post could not go out.")}</p>}
          {entry.url && (
            <a
              href={entry.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-primary underline-offset-4 hover:underline"
            >
              <ExternalLink className="size-4" aria-hidden /> Open the post
            </a>
          )}

          {entry.can_move ? (
            <div className="space-y-2">
              <Label htmlFor={whenId}>Move to</Label>
              <Input
                id={whenId}
                type="datetime-local"
                value={when}
                min={minScheduleValue()}
                disabled={busy}
                onChange={(e) => setWhen(e.target.value)}
              />
              {hints.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Suggested hours (your time):{" "}
                  {hints.map((h) => `${h.platform}: ${h.times.join(", ")}`).join("; ")}. These are
                  starting defaults, not measured from your audience yet.
                </p>
              )}
              {when !== "" && !futureOk && (
                <p className="text-xs text-destructive">Choose a time later than now.</p>
              )}
              {checking && (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" aria-hidden /> Checking the posting rules
                </p>
              )}
              {check?.allow && !checking && (
                <p className="flex items-center gap-1.5 text-xs text-success">
                  <CheckCircle2 className="size-3.5" aria-hidden /> This slot fits the posting rules.
                </p>
              )}
              {blocked && !checking && (
                <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
                  <p>{check.reason}</p>
                  {check.suggested_at && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setWhen(toLocalValue(check.suggested_at))}
                    >
                      Use {new Date(check.suggested_at).toLocaleString()}
                    </Button>
                  )}
                </div>
              )}
              {checkError && <p className="text-xs text-destructive">{checkError}</p>}
            </div>
          ) : (
            <p className="text-muted-foreground">
              This post already started or finished, so it can no longer move.
            </p>
          )}
        </div>

        {entry.can_move && (
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border p-5">
            <Button variant="outline" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            {blocked ? (
              <Button variant="secondary" disabled={busy || !futureOk} onClick={() => void save(true)}>
                Keep this time anyway
              </Button>
            ) : (
              <Button disabled={busy || !futureOk || checking} onClick={() => void save(false)}>
                {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                {busy ? "Saving" : "Save"}
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
