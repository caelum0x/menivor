"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import {
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  PenSquare,
  Radio,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { CalendarToolbar } from "@/components/calendar/CalendarToolbar";
import { BoardGrid } from "@/components/calendar/BoardGrid";
import { EntryDialog } from "@/components/calendar/EntryDialog";
import { ChannelComposer } from "@/components/calendar/ChannelComposer";
import { ConflictBanner, NoticeBanner } from "@/components/calendar/ConflictBanner";
import { entryStatusStyle } from "@/components/calendar/entry-status";
import { entryKey, useCalendarBoard } from "@/components/calendar/use-calendar-board";
import type { BoardEntry } from "@/components/calendar/board-api";
import { LaunchGateNotice, useLaunchGate } from "@/src/shared/launch-gate";
import { MenivorMark } from "@/components/brand/MenivorMark";

const LEGEND: readonly { status: string; label: string }[] = [
  { status: "pending", label: "Scheduled" },
  { status: "publishing", label: "Publishing" },
  { status: "published", label: "Published" },
  { status: "held", label: "Held for review" },
  { status: "failed", label: "Failed" },
  { status: "canceled", label: "Canceled" },
];

/**
 * The publishing calendar: every scheduled and published post (reels to
 * TikTok / Instagram / YouTube, the extended platforms, and Telegram / Discord /
 * Mastodon channels) in the viewer's timezone. Drag a post that has not
 * started onto another day to move it; the posting rules (daily cap, minimum
 * gap) are checked and a refused slot snaps back with the reason and the next
 * open slot. Click any post for details or to pick an exact time.
 */
export default function CalendarPage() {
  const board = useCalendarBoard("month");
  const launch = useLaunchGate();
  const publishGate = launch.gate.publishing;
  const [selected, setSelected] = React.useState<BoardEntry | null>(null);
  const [composerOpen, setComposerOpen] = React.useState(false);

  // Keep the open dialog in sync with the latest copy of its entry.
  const selectedKey = selected ? entryKey(selected) : "";
  const current = React.useMemo(
    () => board.entries.find((e) => entryKey(e) === selectedKey) ?? selected,
    [board.entries, selectedKey, selected],
  );

  const conflict = board.conflict;

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <div className="flex items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/calendar/channels">
                <Radio className="size-4" aria-hidden /> Channels
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
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              <CalendarDays className="size-6 text-primary" aria-hidden />
              Calendar
            </h1>
            <p className="text-sm text-muted-foreground">
              Every scheduled and published post, in your timezone. Drag a post that has not started to another
              day to move it.
            </p>
          </div>
          <Button
            onClick={() => setComposerOpen(true)}
            disabled={launch.status === "loading"}
            title={publishGate.open ? undefined : publishGate.reason}
          >
            <PenSquare className="size-4" aria-hidden /> New channel post
          </Button>
        </div>

        <LaunchGateNotice
          gate={publishGate}
          className="mb-6"
          meanwhile="Posts already on the calendar stay here, and you can still move them to another day."
        />

        {conflict && (
          <ConflictBanner
            conflict={conflict}
            busy={board.movingKey !== null}
            onUseSuggested={(iso) => void board.move(conflict.entry, iso, false)}
            onKeepAnyway={() => void board.move(conflict.entry, conflict.attemptedISO, true)}
            onDismiss={board.clearConflict}
          />
        )}
        {board.notice && !conflict && (
          <NoticeBanner notice={board.notice} onDismiss={board.clearNotice} />
        )}

        <CalendarToolbar
          view={board.view}
          ref={board.ref}
          loading={board.status === "loading"}
          onViewChange={board.setView}
          onPrev={board.goPrev}
          onNext={board.goNext}
          onToday={board.goToday}
          onRefresh={board.reload}
        />

        {board.status === "error" ? (
          <ErrorPanel message={board.error} onRetry={board.reload} />
        ) : (
          <div className={cn("relative transition-opacity", board.status === "loading" && "opacity-60")}>
            {board.status === "idle" ? (
              <GridSkeleton />
            ) : (
              <BoardGrid
                view={board.view}
                days={board.days}
                buckets={board.buckets}
                movingKey={board.movingKey}
                onSelect={setSelected}
                onDropOnDay={board.moveToDay}
              />
            )}
          </div>
        )}

        {board.status === "ready" && board.entries.length === 0 && (
          <p className="mt-4 text-sm text-muted-foreground">
            Nothing scheduled in this period. Schedule a reel from{" "}
            <Link href="/reels" className="text-primary underline-offset-4 hover:underline">your reels</Link>{" "}
            or write a channel post.
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          {LEGEND.map(({ status, label }) => (
            <span key={status} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2.5 rounded-full", entryStatusStyle(status).dot)} aria-hidden />
              {label}
            </span>
          ))}
        </div>
      </section>

      <EntryDialog
        entry={current}
        bestHours={board.bestHours}
        busy={current !== null && board.movingKey === entryKey(current)}
        onMove={board.move}
        onClose={() => setSelected(null)}
      />
      <ChannelComposer
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        onPosted={() => board.reload()}
        publishGate={publishGate}
      />
    </main>
  );
}

function GridSkeleton() {
  return (
    <Card className="overflow-hidden">
      <div className="grid grid-cols-7 [&>*:nth-child(7n)]:border-r-0">
        {Array.from({ length: 35 }).map((_, i) => (
          <div key={i} className="min-h-[6.5rem] space-y-2 border-b border-r border-border p-1.5">
            <Skeleton className="size-6 rounded-full" />
            {i % 3 === 0 && <Skeleton className="h-4 w-full rounded" />}
          </div>
        ))}
      </div>
    </Card>
  );
}

function ErrorPanel({ message, onRetry }: Readonly<{ message: string; onRetry: () => void }>) {
  return (
    <Card className="border-destructive/40 bg-destructive/5">
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
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
