"use client";

import * as React from "react";
import { fetchBetaLaunchStatus, type BetaLaunchStatus } from "./launch";

export interface BetaLaunchState {
  /** Null until the first successful read (or when the read failed). */
  readonly status: BetaLaunchStatus | null;
  readonly loading: boolean;
  readonly failed: boolean;
}

/**
 * Client read of GET /launch/status for readiness-aware CTAs. While it loads
 * (or if it fails) callers keep rendering their default public CTA; the
 * server still enforces the signup gate either way.
 */
export function useBetaLaunchStatus(): BetaLaunchState {
  const [state, setState] = React.useState<BetaLaunchState>({
    status: null,
    loading: true,
    failed: false,
  });

  React.useEffect(() => {
    const controller = new AbortController();
    fetchBetaLaunchStatus(controller.signal)
      .then((status) => setState({ status, loading: false, failed: false }))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setState({ status: null, loading: false, failed: true });
      });
    return () => controller.abort();
  }, []);

  return state;
}
