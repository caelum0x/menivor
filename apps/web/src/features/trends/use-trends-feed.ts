"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { ApiError } from "@/src/shared/api";
import { getTrendsFeed, type FeedTrend } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface UseTrendsFeedResult {
  trends: FeedTrend[];
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}

/**
 * Live server-ranked trends feed. Fetches on mount and exposes `refresh()` so
 * the operator can pull the latest ranking without a page reload.
 */
export function useTrendsFeed(limit = 20): UseTrendsFeedResult {
  const { getToken, isLoaded } = useAuth();
  const [trends, setTrends] = React.useState<FeedTrend[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await getTrendsFeed({ limit }, { token });
      setTrends(res.trends);
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load the trends feed."),
      );
      setTrends([]);
    } finally {
      setLoading(false);
    }
  }, [getToken, limit]);

  React.useEffect(() => {
    if (isLoaded) void refresh();
  }, [isLoaded, refresh]);

  return { trends, loading, error, refresh };
}
