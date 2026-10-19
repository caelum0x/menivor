"use client";

import * as React from "react";
import {
  AlertTriangle,
  CalendarClock,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import { isCancelableSchedule, type ScheduledPublish } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ScheduledCard } from "@/components/schedule/ScheduledCard";
import { formatScheduledAt } from "@/components/schedule/format";
import { useScheduled } from "@/components/schedule/use-scheduled";

export interface ScheduledForJobProps {
  /** The reel/job whose scheduled publishes should be listed. */
  jobId: string;
}

/**
 * The reel-detail CANCEL surface: every scheduled auto-publish that belongs to
 * THIS reel (filtered from GET /me/scheduled by `job_id`), each cancelable via
 * DELETE /me/scheduled/{id} behind an explicit confirmation. Renders nothing
 * once loaded if the reel has no schedules, so it never adds empty chrome to a
 * reel that was never scheduled. Cancel is confirmation-gated to prevent an
 * accidental, irreversible removal of a queued publish.
 */
export function ScheduledForJob({ jobId }: Readonly<ScheduledForJobProps>) {
  const {
    items,
    status,
    error,
    cancelingIds,
    cancelErrors,
    reload,
    cancel,
  } = useScheduled();

  // Only this reel's schedules, newest due-time first.
  const mine = React.useMemo<readonly ScheduledPublish[]>(() => {
    return items
      .filter((item) => item.job_id === jobId)
      .slice()
      .sort((a, b) => {
        const ta = Date.parse(a.scheduled_at);
        const tb = Date.parse(b.scheduled_at);
        return (Number.isNaN(tb) ? 0 : tb) - (Number.isNaN(ta) ? 0 : ta);
      });
  }, [items, jobId]);

  // The schedule the user has asked to cancel, held until they confirm.
  const [pendingCancelId, setPendingCancelId] = React.useState<string | null>(
    null,
  );

  const pending = React.useMemo(
    () => mine.find((item) => item.id === pendingCancelId) ?? null,
    [mine, pendingCancelId],
  );

  // Clicking a card's Cancel opens the confirm gate rather than acting at once.
  const requestCancel = React.useCallback((id: string) => {
    setPendingCancelId(id);
  }, []);

  const closeConfirm = React.useCallback(() => {
    setPendingCancelId(null);
  }, []);

  const confirmCancel = React.useCallback(async () => {
    if (!pendingCancelId) return;
    const id = pendingCancelId;
    setPendingCancelId(null);
    await cancel(id);
  }, [pendingCancelId, cancel]);

  // Nothing scheduled for this reel and no error to report — render nothing.
  if (status === "ready" && mine.length === 0 && !error) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="size-5 text-primary" aria-hidden />
          Scheduled publishes
        </CardTitle>
        <Button
          variant="ghost"
          size="sm"
          onClick={reload}
          disabled={status === "loading"}
        >
          <RefreshCw
            className={
              status === "loading" ? "size-4 animate-spin" : "size-4"
            }
            aria-hidden
          />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {status === "loading" && mine.length === 0 && (
          <div className="space-y-3">
            <Skeleton className="h-24 w-full rounded-lg" />
          </div>
        )}

        {status === "error" && (
          <div className="flex items-start gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-4">
            <AlertTriangle
              className="mt-0.5 size-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div className="flex-1">
              <p className="text-sm font-medium">
                Couldn&apos;t load scheduled publishes
              </p>
              <p className="text-sm text-muted-foreground">{error}</p>
            </div>
            <Button variant="outline" size="sm" onClick={reload}>
              <RefreshCw className="size-4" aria-hidden /> Retry
            </Button>
          </div>
        )}

        {mine.map((item) => (
          <ScheduledCard
            key={item.id}
            item={item}
            canceling={cancelingIds.has(item.id)}
            cancelError={cancelErrors[item.id]}
            onCancel={requestCancel}
          />
        ))}
      </CardContent>

      <CancelConfirmDialog
        schedule={pending}
        onConfirm={() => void confirmCancel()}
        onClose={closeConfirm}
      />
    </Card>
  );
}

interface CancelConfirmDialogProps {
  schedule: ScheduledPublish | null;
  onConfirm: () => void;
  onClose: () => void;
}

/**
 * A focused confirmation modal for canceling a single scheduled publish. Only a
 * still-cancelable (pending/queued) schedule can be confirmed; anything else is
 * treated as a no-op close so a race (it published while the dialog was open)
 * fails safe.
 */
function CancelConfirmDialog({
  schedule,
  onConfirm,
  onClose,
}: Readonly<CancelConfirmDialogProps>) {
  const titleId = React.useId();

  React.useEffect(() => {
    if (!schedule) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [schedule, onClose]);

  if (!schedule) return null;

  const cancelable = isCancelableSchedule(schedule.status);

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
        onClick={onClose}
      />

      <div className="relative z-10 w-full max-w-md rounded-t-2xl border border-border bg-card shadow-lg sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-border p-5">
          <h2
            id={titleId}
            className="flex items-center gap-2 text-lg font-semibold"
          >
            <AlertTriangle className="size-5 text-destructive" aria-hidden />
            Cancel scheduled publish?
          </h2>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="size-4" aria-hidden />
          </Button>
        </div>

        <div className="space-y-2 p-5 text-sm text-muted-foreground">
          {cancelable ? (
            <p>
              This reel will no longer auto-publish at{" "}
              <span className="font-medium text-foreground">
                {formatScheduledAt(schedule.scheduled_at)}
              </span>
              . This can&apos;t be undone, but you can schedule it again later.
            </p>
          ) : (
            <p>
              This publish is already {schedule.status} and can no longer be
              canceled.
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-5">
          <Button variant="outline" onClick={onClose}>
            Keep schedule
          </Button>
          <Button
            variant="destructive"
            disabled={!cancelable}
            onClick={onConfirm}
          >
            <X className="size-4" aria-hidden /> Cancel publish
          </Button>
        </div>
      </div>
    </div>
  );
}
