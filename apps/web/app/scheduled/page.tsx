"use client";

import * as React from "react";
import Link from "next/link";
import { UserButton } from "@/components/auth/clerk-safe";
import { CalendarClock, RefreshCw } from "lucide-react";
import { ScheduledList } from "@/components/schedule/ScheduledList";
import { useScheduled } from "@/components/schedule/use-scheduled";
import { Button } from "@/components/ui/button";
import { MenivorMark } from "@/components/brand/MenivorMark";

/**
 * Full-page list of the caller's scheduled/queued publishes. Shows each
 * schedule's status, target platforms, and due time, and lets the creator cancel
 * any that haven't run yet. A background due-runner (Celery beat) publishes
 * pending schedules once their time arrives; refresh to see the latest states.
 */
export default function ScheduledPage() {
  const { items, status, error, cancelingIds, cancelErrors, reload, cancel } =
    useScheduled();

  const handleCancel = React.useCallback(
    (id: string) => {
      void cancel(id);
    },
    [cancel],
  );

  return (
    <main className="min-h-dvh">
      <header className="border-b border-border">
        <div className="container flex items-center justify-between py-4">
          <Link
            href="/reels"
            className="flex items-center gap-2 font-semibold"
          >
            <MenivorMark variant="gradient" className="size-7" title="Menivor" />
          </Link>
          <UserButton />
        </div>
      </header>

      <section className="container py-12">
        <div className="mx-auto max-w-2xl">
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
                <CalendarClock className="size-7 text-primary" aria-hidden />
                Scheduled
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Reels queued to auto-publish to your platforms.
              </p>
            </div>
            <Button
              variant="outline"
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
          </div>

          <ScheduledList
            status={status}
            items={items}
            error={error}
            cancelingIds={cancelingIds}
            cancelErrors={cancelErrors}
            onRetry={reload}
            onCancel={handleCancel}
          />
        </div>
      </section>
    </main>
  );
}
