/**
 * A small, reusable hook for the platform-admin list screens. It owns the
 * page-window fetch lifecycle — initial load, pull-to-refresh, and append-style
 * "load more" — with loading / empty / error / refreshing states, request
 * cancellation, and stale-response guarding. State is updated immutably (new
 * arrays only). The screens supply a memoized `fetcher`; the hook never knows
 * the shape of a row.
 */

import * as React from "react";

import { isAbortError } from "@/lib/api";
import { describeError } from "@/components/me/errors";

export type AdminListStatus =
  | "loading"
  | "refreshing"
  | "loadingMore"
  | "ready"
  | "error";

/** A page-window fetcher: resolve the rows for one `{ limit, offset }` window. */
export type AdminListFetcher<T> = (
  window: { limit: number; offset: number },
  transport: { token?: string; signal: AbortSignal },
) => Promise<T[]>;

export interface AdminListState<T> {
  readonly items: readonly T[];
  readonly status: AdminListStatus;
  readonly error: string;
  /** True while the very first page is loading (nothing shown yet). */
  readonly initialLoading: boolean;
  /** True when a full page came back last time, so another page may exist. */
  readonly hasMore: boolean;
  refresh: () => void;
  loadMore: () => void;
}

/**
 * Drive a paginated platform-admin listing. `fetcher` MUST be stable (wrap it in
 * `React.useCallback`) — the hook re-runs the initial load whenever it, the
 * `token`, or `pageSize` changes.
 */
export function useAdminList<T>(
  fetcher: AdminListFetcher<T>,
  token: string | undefined,
  pageSize = 50,
): AdminListState<T> {
  const [items, setItems] = React.useState<readonly T[]>([]);
  const [status, setStatus] = React.useState<AdminListStatus>("loading");
  const [error, setError] = React.useState("");
  const [hasMore, setHasMore] = React.useState(false);

  // Latest-request ticket: a stale response (from a superseded load) is dropped.
  const ticketRef = React.useRef(0);
  // Current row count, read without adding `items` to the load() deps.
  const countRef = React.useRef(0);
  React.useEffect(() => {
    countRef.current = items.length;
  }, [items]);

  const load = React.useCallback(
    (mode: "initial" | "refresh" | "more"): (() => void) => {
      const offset = mode === "more" ? countRef.current : 0;
      const ticket = ticketRef.current + 1;
      ticketRef.current = ticket;
      const controller = new AbortController();

      setError("");
      setStatus(
        mode === "refresh"
          ? "refreshing"
          : mode === "more"
            ? "loadingMore"
            : "loading",
      );

      fetcher(
        { limit: pageSize, offset },
        { token, signal: controller.signal },
      )
        .then((page) => {
          if (ticket !== ticketRef.current) return;
          setItems((prev) =>
            mode === "more" ? [...prev, ...page] : [...page],
          );
          setHasMore(page.length >= pageSize);
          setStatus("ready");
        })
        .catch((err: unknown) => {
          if (isAbortError(err) || ticket !== ticketRef.current) return;
          setError(describeError(err));
          setStatus("error");
        });

      return () => controller.abort();
    },
    [fetcher, token, pageSize],
  );

  // Initial load (and reload when the fetcher / token / page size changes).
  React.useEffect(() => {
    const cancel = load("initial");
    return cancel;
  }, [load]);

  const refresh = React.useCallback(() => {
    load("refresh");
  }, [load]);

  const loadMore = React.useCallback(() => {
    if (status !== "ready" || !hasMore) return;
    load("more");
  }, [load, status, hasMore]);

  return {
    items,
    status,
    error,
    initialLoading: status === "loading" && items.length === 0,
    hasMore,
    refresh,
    loadMore,
  };
}
