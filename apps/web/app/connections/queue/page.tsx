"use client";

import * as React from "react";
import { RefreshCw, Send } from "lucide-react";
import type { ScheduledPublish } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { AccountNav } from "@/components/account/AccountNav";
import { AppHeader } from "@/components/account/AppHeader";
import { ScheduledList } from "@/components/schedule/ScheduledList";
import { useScheduled } from "@/components/schedule/use-scheduled";
import { PlatformPostsList } from "../_components/PlatformPostsList";

type QueueFilter = "all" | "upcoming" | "published" | "failed" | "canceled";

interface FilterTab {
  key: QueueFilter;
  label: string;
}

const TABS: readonly FilterTab[] = [
  { key: "all", label: "All" },
  { key: "upcoming", label: "Upcoming" },
  { key: "published", label: "Published" },
  { key: "failed", label: "Failed" },
  { key: "canceled", label: "Canceled" },
];

/** Bucket a schedule's lifecycle status into one of the queue filter tabs. */
function bucketOf(status: ScheduledPublish["status"]): Exclude<QueueFilter, "all"> {
  switch (status) {
    case "published":
      return "published";
    case "failed":
      return "failed";
    case "canceled":
      return "canceled";
    default:
      // pending / queued / publishing (and any future not-yet-terminal state)
      return "upcoming";
  }
}

function matchesFilter(item: ScheduledPublish, filter: QueueFilter): boolean {
  return filter === "all" || bucketOf(item.status) === filter;
}

/**
 * Connections → Publish queue. A single view of every reel the caller has queued
 * to auto-publish to their connected platforms (GET /me/scheduled), grouped by
 * lifecycle into filterable tabs with live counts. A background due-runner
 * publishes upcoming schedules once their time arrives; unstarted schedules can
 * be canceled inline (DELETE /me/scheduled/{id}). Loading / empty / error states
 * are handled by {@link ScheduledList}.
 */
export default function PublishQueuePage() {
  const { items, status, error, cancelingIds, cancelErrors, reload, cancel } =
    useScheduled();
  const [filter, setFilter] = React.useState<QueueFilter>("all");

  const counts = React.useMemo(() => {
    const base: Record<QueueFilter, number> = {
      all: items.length,
      upcoming: 0,
      published: 0,
      failed: 0,
      canceled: 0,
    };
    for (const item of items) base[bucketOf(item.status)] += 1;
    return base;
  }, [items]);

  const visible = React.useMemo(
    () => items.filter((item) => matchesFilter(item, filter)),
    [items, filter],
  );

  const handleCancel = React.useCallback(
    (id: string) => {
      void cancel(id);
    },
    [cancel],
  );

  return (
    <main className="min-h-dvh">
      <AppHeader />

      <section className="container py-10">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-muted-foreground">
                Connections
              </p>
              <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight">
                <Send className="size-7 text-primary" aria-hidden />
                Publish queue
              </h1>
              <p className="mt-2 max-w-xl text-muted-foreground">
                Every reel queued to auto-publish to your connected platforms.
                Cancel anything that hasn&apos;t gone out yet.
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

          <AccountNav />

          <div
            role="tablist"
            aria-label="Filter publish queue"
            className="mb-6 flex flex-wrap gap-1 rounded-lg border border-border bg-secondary/40 p-1"
          >
            {TABS.map((tab) => {
              const active = filter === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setFilter(tab.key)}
                  className={
                    active
                      ? "flex items-center gap-2 rounded-md bg-background px-3 py-1.5 text-sm font-medium text-foreground shadow-sm"
                      : "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
                  }
                >
                  {tab.label}
                  <span className="rounded-full bg-secondary px-1.5 py-0.5 text-xs tabular-nums text-muted-foreground">
                    {counts[tab.key]}
                  </span>
                </button>
              );
            })}
          </div>

          <ScheduledList
            status={status}
            items={visible}
            error={error}
            cancelingIds={cancelingIds}
            cancelErrors={cancelErrors}
            onRetry={reload}
            onCancel={handleCancel}
          />

          <PlatformPostsList />
        </div>
      </section>
    </main>
  );
}
