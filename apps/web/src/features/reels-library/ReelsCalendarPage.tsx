"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  Film,
  RefreshCw,
} from "lucide-react";
import type { CalendarEntry } from "@/lib/calendar";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useCalendar } from "@/components/calendar/use-calendar";
import { CalendarToolbar } from "@/components/calendar/CalendarToolbar";
import { CalendarGrid } from "@/components/calendar/CalendarGrid";
import { RescheduleDialog } from "@/components/calendar/RescheduleDialog";
import { entryStatusStyle } from "@/components/calendar/entry-status";
import { ScheduledList } from "@/components/schedule/ScheduledList";
import { useScheduled } from "@/components/schedule/use-scheduled";
import { MenivorMark } from "@/components/brand/MenivorMark";

const LEGEND: readonly { status: string; label: string }[] = [
  { status: "pending", label: "Pending" },
  { status: "publishing", label: "Publishing" },
  { status: "published", label: "Published" },
  { status: "failed", label: "Failed" },
  { status: "canceled", label: "Canceled" },
];

/**
 * The Reels SCHEDULE calendar. The month/week grid renders the caller's
 * scheduled + published reels colour-coded by status; clicking a still-pending
 * publish opens a control to reschedule it (PATCH /me/calendar/{id}). Below the
 * grid, the queue list lets the creator cancel any pending publish
 * (DELETE /me/scheduled/{id}). Both surfaces are strictly owner-scoped
 * server-side.
 */
export function ReelsCalendarPage() {
  const {
    view,
    setView,
    ref,
    goPrev,
    goNext,
    goToday,
    days,
    buckets,
    status,
    error,
    reload,
    reschedule,
    reschedulingId,
    rescheduleError,
    clearRescheduleError,
  } = useCalendar("month");

  const scheduled = useScheduled();

  const [selected, setSelected] = React.useState<CalendarEntry | null>(null);

  const handleSelect = React.useCallback(
    (entry: CalendarEntry) => {
      clearRescheduleError();
      setSelected(entry);
    },
    [clearRescheduleError],
  );

  const handleClose = React.useCallback(() => {
    clearRescheduleError();
    setSelected(null);
  }, [clearRescheduleError]);

  const handleSubmit = React.useCallback(
    async (scheduledAtISO: string): Promise<boolean> => {
      if (!selected) return false;
      const ok = await reschedule(selected.id, scheduledAtISO);
      // Keep the queue list consistent with the grid after a successful move.
      if (ok) scheduled.reload();
      return ok;
    },
    [selected, reschedule, scheduled],
  );

  const handleCancel = React.useCallback(
    (id: string) => {
      // `cancel` resolves once the DELETE settles (it surfaces failures via its
      // own per-row error state, not by rejecting). Refetch the grid afterward
      // so a cancelled publish disappears from the month view too.
      void scheduled.cancel(id).then(() => {
        reload();
      });
    },
    [scheduled, reload],
  );

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-3">
            <Button asChild variant="outline" size="sm">
              <Link href="/reels">
                <Film className="size-4" aria-hidden /> Reel library
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/scheduled">
                <CalendarClock className="size-4" aria-hidden /> Scheduled
              </Link>
            </Button>
            <UserButton />
          </div>
        </div>
      </header>

      <section className="container py-8">
        <div className="mb-6">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <CalendarDays className="size-6 text-primary" aria-hidden />
            Schedule
          </h1>
          <p className="text-sm text-muted-foreground">
            Your scheduled and published reels, in your timezone. Click a pending
            publish to reschedule it, or cancel one from the queue below.
          </p>
        </div>

        <CalendarToolbar
          view={view}
          ref={ref}
          loading={status === "loading"}
          onViewChange={setView}
          onPrev={goPrev}
          onNext={goNext}
          onToday={goToday}
          onRefresh={reload}
        />

        {status === "error" ? (
          <ErrorPanel message={error} onRetry={reload} />
        ) : (
          <div
            className={cn(
              "relative transition-opacity",
              status === "loading" && "opacity-60",
            )}
          >
            {status === "idle" ? (
              <CalendarSkeleton />
            ) : (
              <CalendarGrid
                view={view}
                days={days}
                buckets={buckets}
                onSelect={handleSelect}
              />
            )}
          </div>
        )}

        <Legend />

        <div className="mt-10">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
                <CalendarClock className="size-5 text-primary" aria-hidden />
                Upcoming queue
              </h2>
              <p className="text-sm text-muted-foreground">
                Reels queued to auto-publish. Cancel any that haven&apos;t run
                yet.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={scheduled.reload}
              disabled={scheduled.status === "loading"}
            >
              <RefreshCw
                className={
                  scheduled.status === "loading"
                    ? "size-4 animate-spin"
                    : "size-4"
                }
                aria-hidden
              />
              Refresh
            </Button>
          </div>

          <div className="max-w-2xl">
            <ScheduledList
              status={scheduled.status}
              items={scheduled.items}
              error={scheduled.error}
              cancelingIds={scheduled.cancelingIds}
              cancelErrors={scheduled.cancelErrors}
              onRetry={scheduled.reload}
              onCancel={handleCancel}
            />
          </div>
        </div>
      </section>

      <RescheduleDialog
        entry={selected}
        submitting={selected !== null && reschedulingId === selected.id}
        error={rescheduleError}
        onSubmit={handleSubmit}
        onClose={handleClose}
      />
    </main>
  );
}

function Legend() {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {LEGEND.map(({ status, label }) => (
        <span key={status} className="inline-flex items-center gap-1.5">
          <span
            className={cn(
              "size-2.5 rounded-full",
              entryStatusStyle(status).dot,
            )}
            aria-hidden
          />
          {label}
        </span>
      ))}
    </div>
  );
}

function CalendarSkeleton() {
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-cols-7 border-b border-border bg-muted/40">
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="border-r border-border px-2 py-2 last:border-r-0"
          >
            <Skeleton className="mx-auto h-3 w-8" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 [&>*:nth-child(7n)]:border-r-0">
        {Array.from({ length: 35 }).map((_, i) => (
          <div
            key={i}
            className="min-h-[6.5rem] space-y-2 border-b border-r border-border p-1.5"
          >
            <Skeleton className="size-6 rounded-full" />
            {i % 3 === 0 && <Skeleton className="h-4 w-full rounded" />}
          </div>
        ))}
      </div>
    </Card>
  );
}

function ErrorPanel({
  message,
  onRetry,
}: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-destructive"
            aria-hidden
          />
          <div>
            <p className="font-medium">Couldn&apos;t load your calendar</p>
            <p className="text-sm text-muted-foreground">{message}</p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </CardContent>
    </Card>
  );
}
