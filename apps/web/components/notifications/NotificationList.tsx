"use client";

import { AlertTriangle, BellOff, RefreshCw } from "lucide-react";
import type { Notification } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { NotificationItem } from "@/components/notifications/NotificationItem";
import type { NotificationListStatus } from "@/components/notifications/use-notifications";

interface NotificationListProps {
  status: NotificationListStatus;
  notifications: readonly Notification[];
  errorMessage: string;
  onRetry: () => void;
  onSelect: (notification: Notification) => void;
}

/**
 * Renders the notification center body across its load states: skeletons while
 * loading, a retryable error panel, an empty state, or the list of rows. Purely
 * presentational — all data + actions are owned by the caller (bell or page).
 */
export function NotificationList({
  status,
  notifications,
  errorMessage,
  onRetry,
  onSelect,
}: NotificationListProps) {
  if (status === "loading" || status === "idle") {
    return (
      <div className="divide-y divide-border/60">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-start gap-3 px-4 py-3">
            <Skeleton className="size-5 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3.5 w-2/3" />
              <Skeleton className="h-3 w-full" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
        <AlertTriangle className="size-6 text-destructive" aria-hidden />
        <p className="text-sm text-muted-foreground">
          {errorMessage || "Couldn't load your notifications."}
        </p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="size-4" aria-hidden /> Try again
        </Button>
      </div>
    );
  }

  if (notifications.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
        <span className="flex size-11 items-center justify-center rounded-full bg-secondary/60">
          <BellOff className="size-5 text-muted-foreground" aria-hidden />
        </span>
        <div>
          <p className="text-sm font-medium">You&apos;re all caught up</p>
          <p className="text-sm text-muted-foreground">
            Notifications about your reels and credits will show up here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-border/60">
      {notifications.map((notification) => (
        <li key={notification.id}>
          <NotificationItem notification={notification} onSelect={onSelect} />
        </li>
      ))}
    </ul>
  );
}
