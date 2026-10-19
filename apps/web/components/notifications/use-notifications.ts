"use client";

import * as React from "react";
import {
  ApiError,
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import type { Notification } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

/** How often the unread badge is polled (~20s per the spec). */
export const UNREAD_POLL_INTERVAL_MS = 20_000;

/** Default page size when loading the notification center. */
const LIST_LIMIT = 30;

export type NotificationListStatus = "idle" | "loading" | "ready" | "error";

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

export interface UseNotificationsResult {
  /** Live total unread count (badge source of truth). */
  count: number;
  /** Load state of the notification list. */
  status: NotificationListStatus;
  /** The loaded notifications, newest first. */
  notifications: readonly Notification[];
  /** Human-readable error for the list, when `status === "error"`. */
  errorMessage: string;
  /** (Re)load the notification list (e.g. when the center opens). */
  loadList: () => void;
  /** Re-poll only the unread count. */
  refreshCount: () => void;
  /** Mark one notification read (optimistic; re-syncs on failure). */
  markRead: (id: string) => Promise<void>;
  /** Mark every notification read (optimistic; re-syncs on failure). */
  markAllRead: () => Promise<void>;
}

export interface UseNotificationsOptions {
  /** Poll cadence for the unread count in ms (default ~20s). */
  pollIntervalMs?: number;
  /** Page size for the list (default 30). */
  limit?: number;
}

/**
 * Owns the caller's in-app notifications: polls the unread count on an interval
 * (and on tab refocus), lazily loads the list, and exposes optimistic
 * mark-read / mark-all-read mutators. Every state transition replaces state with
 * a fresh value — nothing is mutated. All fetches are best-effort: count polling
 * never surfaces an error (the badge simply lags), while the list exposes a
 * retryable error state.
 */
export function useNotifications(
  options: UseNotificationsOptions = {},
): UseNotificationsResult {
  const pollIntervalMs = options.pollIntervalMs ?? UNREAD_POLL_INTERVAL_MS;
  const limit = options.limit ?? LIST_LIMIT;

  const getApiToken = useApiToken();
  const [count, setCount] = React.useState(0);
  const [status, setStatus] = React.useState<NotificationListStatus>("idle");
  const [notifications, setNotifications] = React.useState<
    readonly Notification[]
  >([]);
  const [errorMessage, setErrorMessage] = React.useState("");

  // Guards against setState after unmount (long-lived polling component).
  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refreshCount = React.useCallback(async () => {
    try {
      const token = await getApiToken();
      const next = await getUnreadCount({ token });
      if (mountedRef.current) setCount(next);
    } catch {
      // Best-effort: keep the last known count; the next poll retries.
    }
  }, [getApiToken]);

  const loadList = React.useCallback(async () => {
    setStatus("loading");
    setErrorMessage("");
    try {
      const token = await getApiToken();
      const result = await listNotifications({ limit }, { token });
      if (!mountedRef.current) return;
      setNotifications(result.notifications);
      setCount(result.unread_count);
      setStatus("ready");
    } catch (err) {
      if (!mountedRef.current) return;
      setErrorMessage(
        errorMessageOf(err, "Couldn't load your notifications."),
      );
      setStatus("error");
    }
  }, [getApiToken, limit]);

  // Poll the unread count on an interval, plus once on mount and on refocus.
  React.useEffect(() => {
    void refreshCount();
    const timer = setInterval(() => void refreshCount(), pollIntervalMs);

    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshCount();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [refreshCount, pollIntervalMs]);

  const markRead = React.useCallback(
    async (id: string): Promise<void> => {
      // Optimistic: flip the row and decrement the badge immediately.
      let wasUnread = false;
      setNotifications((prev) =>
        prev.map((n) => {
          if (n.id !== id) return n;
          if (!n.read) wasUnread = true;
          return { ...n, read: true };
        }),
      );
      if (wasUnread) setCount((c) => Math.max(0, c - 1));

      try {
        const token = await getApiToken();
        await markNotificationRead(id, { token });
      } catch {
        // Re-sync from the server if the optimistic update was wrong.
        void refreshCount();
        void loadList();
      }
    },
    [getApiToken, refreshCount, loadList],
  );

  const markAllRead = React.useCallback(async (): Promise<void> => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    setCount(0);
    try {
      const token = await getApiToken();
      await markAllNotificationsRead({ token });
    } catch {
      void refreshCount();
      void loadList();
    }
  }, [getApiToken, refreshCount, loadList]);

  return {
    count,
    status,
    notifications,
    errorMessage,
    loadList: () => void loadList(),
    refreshCount: () => void refreshCount(),
    markRead,
    markAllRead,
  };
}
