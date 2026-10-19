"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bell, CheckCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Notification } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { NotificationList } from "@/components/notifications/NotificationList";
import { notificationHref } from "@/components/notifications/format";
import { useNotifications } from "@/components/notifications/use-notifications";

/** Cap the number shown in the badge; anything higher renders as "N+". */
const BADGE_CAP = 9;

function badgeLabel(count: number): string {
  return count > BADGE_CAP ? `${BADGE_CAP}+` : String(count);
}

/**
 * Notification bell for the app header: shows the unread count (polled ~20s) and
 * opens a dropdown center listing recent notifications. Clicking a notification
 * marks it read and deep-links to the related job/page when available. Includes
 * a "mark all read" action and a link to the full notification center.
 *
 * Render this only for signed-in users (e.g. inside Clerk's `<SignedIn>`) — the
 * underlying endpoints are caller-scoped and auth-gated.
 */
export function NotificationBell() {
  const router = useRouter();
  const {
    count,
    status,
    notifications,
    errorMessage,
    loadList,
    markRead,
    markAllRead,
  } = useNotifications();

  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const toggle = React.useCallback(() => {
    setOpen((prev) => {
      const next = !prev;
      if (next) loadList();
      return next;
    });
  }, [loadList]);

  // Close on outside click or Escape while the dropdown is open.
  React.useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const handleSelect = React.useCallback(
    (notification: Notification) => {
      setOpen(false);
      if (!notification.read) void markRead(notification.id);
      const href = notificationHref(notification);
      if (href) router.push(href);
    },
    [markRead, router],
  );

  const hasUnread = count > 0;

  return (
    <div ref={containerRef} className="relative">
      <Button
        variant="ghost"
        size="icon"
        onClick={toggle}
        aria-label={
          hasUnread
            ? `Notifications, ${count} unread`
            : "Notifications"
        }
        aria-haspopup="menu"
        aria-expanded={open}
        className="relative"
      >
        <Bell className="size-5" aria-hidden />
        {hasUnread && (
          <span
            className={cn(
              "absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center",
              "rounded-full bg-primary px-1 text-[10px] font-semibold leading-4",
              "text-primary-foreground",
            )}
            aria-hidden
          >
            {badgeLabel(count)}
          </span>
        )}
      </Button>

      {open && (
        <div
          role="menu"
          aria-label="Notifications"
          className={cn(
            "absolute right-0 z-50 mt-2 w-80 max-w-[calc(100vw-2rem)] overflow-hidden",
            "rounded-lg border border-border bg-card text-card-foreground shadow-lg",
          )}
        >
          <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">Notifications</p>
            <button
              type="button"
              onClick={() => void markAllRead()}
              disabled={!hasUnread}
              className={cn(
                "inline-flex items-center gap-1.5 text-xs font-medium transition-colors",
                "text-muted-foreground hover:text-foreground",
                "disabled:pointer-events-none disabled:opacity-40",
              )}
            >
              <CheckCheck className="size-3.5" aria-hidden /> Mark all read
            </button>
          </div>

          <div className="max-h-96 overflow-y-auto">
            <NotificationList
              status={status}
              notifications={notifications}
              errorMessage={errorMessage}
              onRetry={loadList}
              onSelect={handleSelect}
            />
          </div>

          <div className="border-t border-border px-4 py-2 text-center">
            <Link
              href="/notifications"
              onClick={() => setOpen(false)}
              className="text-xs font-medium text-primary hover:underline"
            >
              View all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
