"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, CalendarClock, Plus, RefreshCw } from "lucide-react";
import type { ScheduledPublish } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ScheduledCard } from "@/components/schedule/ScheduledCard";
import type { ScheduledStatus } from "@/components/schedule/use-scheduled";

export interface ScheduledListProps {
  status: ScheduledStatus;
  items: readonly ScheduledPublish[];
  error: string;
  cancelingIds: ReadonlySet<string>;
  cancelErrors: Readonly<Record<string, string>>;
  onRetry: () => void;
  onCancel: (id: string) => void;
}

/**
 * Renders the scheduled-publishes list across its load/error/empty/ready states.
 * Purely presentational — all data and mutators are supplied by the parent
 * (see {@link useScheduled}).
 */
export function ScheduledList({
  status,
  items,
  error,
  cancelingIds,
  cancelErrors,
  onRetry,
  onCancel,
}: Readonly<ScheduledListProps>) {
  if (status === "loading" || status === "idle") {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (status === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <AlertTriangle
              className="mt-0.5 size-5 shrink-0 text-destructive"
              aria-hidden
            />
            <div>
              <p className="font-medium">Couldn&apos;t load your schedule</p>
              <p className="text-sm text-muted-foreground">{error}</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="size-4" aria-hidden /> Try again
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-primary/10">
            <CalendarClock className="size-6 text-primary" aria-hidden />
          </span>
          <div>
            <p className="font-medium">Nothing scheduled</p>
            <p className="text-sm text-muted-foreground">
              Open a finished reel and choose &ldquo;Schedule publish&rdquo; to
              auto-post it later.
            </p>
          </div>
          <Button asChild>
            <Link href="/reels">
              <Plus className="size-4" aria-hidden /> Go to your reels
            </Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ScheduledCard
          key={item.id}
          item={item}
          canceling={cancelingIds.has(item.id)}
          cancelError={cancelErrors[item.id]}
          onCancel={onCancel}
        />
      ))}
    </div>
  );
}
