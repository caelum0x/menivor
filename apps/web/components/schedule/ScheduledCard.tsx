"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowUpRight, CalendarClock, Film, Loader2, X } from "lucide-react";
import {
  isCancelableSchedule,
  type ScheduledPublish,
} from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScheduleStatusBadge } from "@/components/schedule/ScheduleStatusBadge";
import { platformLabel } from "@/components/schedule/platforms";
import { formatRelative, formatScheduledAt } from "@/components/schedule/format";
import { safeServerText } from "@/src/shared/errors/friendly";

export interface ScheduledCardProps {
  item: ScheduledPublish;
  canceling: boolean;
  cancelError?: string;
  onCancel: (id: string) => void;
}

/**
 * A single scheduled-publish row: status badge, target platforms, due time, a
 * deep link to the source reel, and a cancel action while the schedule is still
 * pending. Props are read-only.
 */
export function ScheduledCard({
  item,
  canceling,
  cancelError,
  onCancel,
}: Readonly<ScheduledCardProps>) {
  const cancelable = isCancelableSchedule(item.status);
  const shortJob = item.job_id.slice(0, 8);

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <ScheduleStatusBadge status={item.status} />
            <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
              <CalendarClock className="size-3.5" aria-hidden />
              {formatScheduledAt(item.scheduled_at)}
              {cancelable && (
                <span className="text-xs">
                  ({formatRelative(item.scheduled_at)})
                </span>
              )}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {item.platforms.length > 0 ? (
              item.platforms.map((platform) => (
                <span
                  key={platform}
                  className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-xs font-medium"
                >
                  {platformLabel(platform)}
                </span>
              ))
            ) : (
              <span className="text-xs text-muted-foreground">
                No platforms
              </span>
            )}
            {item.youtube_privacy_status && (
              <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-xs text-secondary-foreground">
                YouTube: {item.youtube_privacy_status}
              </span>
            )}
          </div>

          <Link
            href={`/jobs/${item.job_id}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
          >
            <Film className="size-3.5" aria-hidden />
            <span className="font-mono">{shortJob}</span>
            <ArrowUpRight className="size-3" aria-hidden />
          </Link>

          {item.status === "failed" && item.error && (
            <p
              className="line-clamp-2 text-xs text-destructive"
            >
              {safeServerText(item.error, "This post could not go out.")}
            </p>
          )}
          {cancelError && (
            <p className="text-xs text-destructive">{cancelError}</p>
          )}
        </div>

        {cancelable && (
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            onClick={() => onCancel(item.id)}
            disabled={canceling}
          >
            {canceling ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : (
              <X className="size-4" aria-hidden />
            )}
            {canceling ? "Canceling…" : "Cancel"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
