"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { getCredits, type Credits } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface UseCreditsResult {
  credits: Credits | null;
  loading: boolean;
  error: string;
  /** Re-fetch the wallet balance (call after a billed generation settles). */
  refresh: () => Promise<void>;
}

/**
 * Live wallet balance for the media gateway. Fetches once on mount and exposes a
 * `refresh()` the caller invokes after a generation settles, so the displayed
 * balance reflects the debit without a page reload.
 */
export function useCredits(): UseCreditsResult {
  const { getToken } = useAuth();
  const [credits, setCredits] = React.useState<Credits | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      setCredits(await getCredits({ token }));
    } catch (err) {
      setError(friendlyErrorMessage(err, "Failed to load balance."));
      setCredits(null);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  return { credits, loading, error, refresh };
}
