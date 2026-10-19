/**
 * Loading lifecycle for a single catalog GET, with pull-to-refresh support.
 *
 * Owns the loading / ready / error status plus a separate `refreshing` flag so
 * a pull-to-refresh keeps the current list on screen (rather than flashing the
 * full-screen spinner). The `fetcher` MUST be memoised by the caller (usually
 * `useCallback` keyed on the auth token) — the hook reloads whenever the
 * fetcher identity changes.
 */

import { useCallback, useEffect, useState } from "react";

import { isAbortError } from "@/lib/api";
import { describeError } from "@/components/me/errors";
import type { ResourceStatus } from "@/components/me/use-resource";

export interface CatalogResource<T> {
  status: ResourceStatus;
  data: T | null;
  error: string;
  refreshing: boolean;
  reload: () => void;
  refresh: () => void;
}

export function useCatalogResource<T>(fetcher: () => Promise<T>): CatalogResource<T> {
  const [status, setStatus] = useState<ResourceStatus>("loading");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const refresh = useCallback(() => {
    setRefreshing(true);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let active = true;
    if (data === null) setStatus("loading");
    setError("");

    fetcher()
      .then((result) => {
        if (!active) return;
        setData(result);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(describeError(err, "Failed to load."));
        setStatus("error");
      })
      .finally(() => {
        if (active) setRefreshing(false);
      });

    return () => {
      active = false;
    };
    // `data` intentionally omitted: we only branch on its first-load emptiness.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetcher, nonce]);

  return { status, data, error, refreshing, reload, refresh };
}
