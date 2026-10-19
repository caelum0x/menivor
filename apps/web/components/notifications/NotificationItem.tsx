"use client";

import { cn } from "@/lib/utils";
import type { Notification } from "@/lib/types";
import {
  formatRelativeTime,
  kindMeta,
  notificationHref,
} from "@/components/notifications/format";

interface NotificationItemProps {
  notification: Notification;
  /**
   * Invoked when the row is activated (click / Enter / Space). The parent marks
   * it read and deep-links when `notificationHref` resolves a target.
   */
  onSelect: (notification: Notification) => void;
}

/**
 * A single notification row: kind icon, title, body, and relative time. Unread
 * rows carry a subtle highlight and a leading dot. The whole row is an
 * accessible button so keyboard users can open it too.
 */
export function NotificationItem({
  notification,
  onSelect,
}: NotificationItemProps) {
  const { icon: Icon, accent } = kindMeta(notification.kind);
  const time = formatRelativeTime(notification.created_at);
  const hasLink = notificationHref(notification) !== null;

  return (
    <button
      type="button"
      onClick={() => onSelect(notification)}
      aria-label={`${notification.title}${
        notification.read ? "" : " (unread)"
      }`}
      className={cn(
        "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors",
        "hover:bg-secondary/50 focus-visible:outline-none focus-visible:bg-secondary/60",
        !notification.read && "bg-primary/5",
      )}
    >
      <span className={cn("mt-0.5 shrink-0", accent)}>
        <Icon className="size-5" aria-hidden />
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span
            className={cn(
              "truncate text-sm",
              notification.read ? "font-medium" : "font-semibold",
            )}
          >
            {notification.title}
          </span>
          {!notification.read && (
            <span
              className="ml-auto size-2 shrink-0 rounded-full bg-primary"
              aria-hidden
            />
          )}
        </span>
        {notification.body && (
          <span className="mt-0.5 line-clamp-2 block text-sm text-muted-foreground">
            {notification.body}
          </span>
        )}
        <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          {time && <span>{time}</span>}
          {hasLink && (
            <span className="text-primary" aria-hidden>
              View →
            </span>
          )}
        </span>
      </span>
    </button>
  );
}
