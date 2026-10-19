import { useCallback, useEffect, useState } from "react";

import { getLaunchStatus, isAbortError } from "@/lib/api";
import type { LaunchStatus } from "@/lib/types";

export interface LaunchStatusState {
  /** The server-owned launch gates, or null before the first successful load. */
  status: LaunchStatus | null;
  /** True while the first load is in flight. */
  loading: boolean;
  /** True while a manual refresh is in flight (initial load excluded). */
  refreshing: boolean;
  /** A user-facing error message, or "" when there is none. */
  error: string;
  /** Re-fetch the launch status; used by pull-to-refresh and retry. */
  refresh: () => void;
}

/**
 * Shared loader for GET /launch/status — the fail-closed launch gates that
 * explain why checkout / publishing / signup may be blocked. Auto-loads on
 * mount (and when the token changes) and exposes a `refresh` for pull-to-refresh
 * and retry. Aborts its in-flight request on unmount to avoid setState leaks.
 */
export function useLaunchStatus(token: string | undefined): LaunchStatusState {
  const [status, setStatus] = useState<LaunchStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string>("");
  const [nonce, setNonce] = useState<number>(0);

  const refresh = useCallback(() => {
    setRefreshing(true);
    setNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setError("");

    void getLaunchStatus({ token, signal: controller.signal })
      .then((next) => {
        if (!active) return;
        setStatus(next);
        setError("");
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        setError(
          err instanceof Error
            ? err.message
            : "Could not check the launch status.",
        );
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
        setRefreshing(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [token, nonce]);

  return { status, loading, refreshing, error, refresh };
}
