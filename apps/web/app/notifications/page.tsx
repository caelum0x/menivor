"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UserButton } from "@/components/auth/clerk-safe";
import { CheckCheck, RefreshCw } from "lucide-react";
import type { Notification } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { NotificationList } from "@/components/notifications/NotificationList";
import { notificationHref } from "@/components/notifications/format";
import { useNotifications } from "@/components/notifications/use-notifications";
import { MenivorMark } from "@/components/brand/MenivorMark";

/**
 * Full-page notification center. Lists the caller's notifications with the same
 * load/error/empty states as the bell dropdown, plus mark-all-read and refresh.
 * Clicking a notification marks it read and deep-links when a target resolves.
 */
export default function NotificationsPage() {
  const router = useRouter();
  const {
    count,
    status,
    notifications,
    errorMessage,
    loadList,
    markRead,
    markAllRead,
  } = useNotifications({ limit: 100 });

  // Load the list once on mount (the hook starts idle until asked).
  React.useEffect(() => {
    loadList();
    // loadList is stable for the lifetime of the hook; run once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelect = React.useCallback(
    (notification: Notification) => {
      if (!notification.read) void markRead(notification.id);
      const href = notificationHref(notification);
      if (href) router.push(href);
    },
    [markRead, router],
  );

  const hasUnread = count > 0;

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
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-bold tracking-tight">
                  Notifications
                </h1>
                {hasUnread && (
                  <Badge variant="default" className="px-2.5 py-0.5">
                    {count} unread
                  </Badge>
                )}
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Updates about your reels, credits, and referrals.
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void markAllRead()}
                disabled={!hasUnread}
              >
                <CheckCheck className="size-4" aria-hidden /> Mark all read
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={loadList}
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
          </div>

          <Card className="overflow-hidden">
            <NotificationList
              status={status}
              notifications={notifications}
              errorMessage={errorMessage}
              onRetry={loadList}
              onSelect={handleSelect}
            />
          </Card>
        </div>
      </section>
    </main>
  );
}
