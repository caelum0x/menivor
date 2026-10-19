"use client";

import * as React from "react";
import { ApiError, cancelScheduled, listScheduled } from "@/lib/api";
import type { ScheduledPublish, ScheduledPublishStatus } from "@/lib/types";
import { useApiToken } from "@/lib/use-api-token";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export type ScheduledStatus = "idle" | "loading" | "ready" | "error";

export interface UseScheduledResult {
  items: readonly ScheduledPublish[];
  status: ScheduledStatus;
  error: string;
  /** Ids currently being canceled (for per-row spinners). */
  cancelingIds: ReadonlySet<string>;
  /** Per-row cancel error keyed by schedule id. */
  cancelErrors: Readonly<Record<string, string>>;
  reload: () => void;
  cancel: (id: string) => Promise<void>;
}

function errorMessageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return friendlyErrorMessage(err);
  if (err instanceof Error) return friendlyErrorMessage(err);
  return fallback;
}

/**
 * Loads the caller's scheduled publishes (GET /me/scheduled), optionally
 * filtered by `status`, and exposes a `cancel` mutator (DELETE
 * /me/scheduled/{id}). State is only ever replaced, never mutated in place;
 * a successful cancel flips the affected row to `"canceled"` locally so the UI
 * stays consistent without a full refetch.
 */
export function useScheduled(
  status?: ScheduledPublishStatus,
): UseScheduledResult {
  const getApiToken = useApiToken();

  const [items, setItems] = React.useState<readonly ScheduledPublish[]>([]);
  const [loadStatus, setLoadStatus] = React.useState<ScheduledStatus>("idle");
  const [error, setError] = React.useState<string>("");
  const [reloadNonce, setReloadNonce] = React.useState(0);
  const [cancelingIds, setCancelingIds] = React.useState<ReadonlySet<string>>(
    new Set(),
  );
  const [cancelErrors, setCancelErrors] = React.useState<
    Readonly<Record<string, string>>
  >({});

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      setLoadStatus("loading");
      setError("");
      try {
        const token = await getApiToken();
        const list = await listScheduled(status, {
          token,
          signal: controller.signal,
        });
        if (cancelled) return;
        setItems(list);
        setLoadStatus("ready");
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(errorMessageOf(err, "Couldn't load your scheduled publishes."));
        setLoadStatus("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getApiToken, status, reloadNonce]);

  const reload = React.useCallback(() => {
    setReloadNonce((n) => n + 1);
  }, []);

  const cancel = React.useCallback(
    async (id: string): Promise<void> => {
      setCancelErrors((prev) => {
        if (!(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setCancelingIds((prev) => {
        const next = new Set(prev);
        next.add(id);
        return next;
      });

      try {
        const token = await getApiToken();
        await cancelScheduled(id, { token });
        if (!mountedRef.current) return;
        setItems((prev) =>
          prev.map((item) =>
            item.id === id ? { ...item, status: "canceled" } : item,
          ),
        );
      } catch (err) {
        if (!mountedRef.current) return;
        setCancelErrors((prev) => ({
          ...prev,
          [id]: errorMessageOf(err, "Failed to cancel this schedule."),
        }));
      } finally {
        if (mountedRef.current) {
          setCancelingIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
        }
      }
    },
    [getApiToken],
  );

  return {
    items,
    status: loadStatus,
    error,
    cancelingIds,
    cancelErrors,
    reload,
    cancel,
  };
}
