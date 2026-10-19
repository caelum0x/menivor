"use client";

import * as React from "react";
import { useAuth } from "@/components/auth/clerk-safe";

import { ApiError } from "@/src/shared/api";
import { getRecommendedTrends, getRecommendedTrendsByKind, getViralTemplates } from "./api";
import type { FeedTrend, TemplateSummary } from "./api";
import { friendlyErrorMessage } from "@/src/shared/errors/friendly";

export interface DiscoverData {
  allTrends: FeedTrend[];
  soundTrends: FeedTrend[];
  hashtagTrends: FeedTrend[];
  formatTrends: FeedTrend[];
  templates: TemplateSummary[];
}

export interface UseDiscoverResult {
  data: DiscoverData;
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}

const EMPTY: DiscoverData = {
  allTrends: [],
  soundTrends: [],
  hashtagTrends: [],
  formatTrends: [],
  templates: [],
};

/**
 * Load all discover-hub data in parallel: the live trends feed and viral
 * format templates. Filters the trend feed by `kind` client-side so we only
 * make two round-trips instead of four.
 */
export function useDiscover(): UseDiscoverResult {
  const { getToken, isLoaded } = useAuth();
  const [data, setData] = React.useState<DiscoverData>(EMPTY);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const opts = { token };

      const [trendsRes, templatesRes] = await Promise.all([
        getRecommendedTrends({ limit: 40 }, opts),
        getViralTemplates(opts),
      ]);

      const allTrends = trendsRes.trends;
      setData({
        allTrends,
        soundTrends: allTrends.filter((t) => t.kind === "sound"),
        hashtagTrends: allTrends.filter((t) => t.kind === "hashtag"),
        formatTrends: allTrends.filter((t) => t.kind === "format"),
        templates: templatesRes.templates,
      });
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load discover data."),
      );
      setData(EMPTY);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void refresh();
  }, [isLoaded, refresh]);

  return { data, loading, error, refresh };
}

export interface UseDiscoverKindResult {
  trends: FeedTrend[];
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}

/**
 * Fetch the live recommended-trends feed filtered to a single `kind`.
 * Suitable for the per-kind sub-pages (/discover/sounds, /discover/hashtags,
 * /discover/creators). Uses `getRecommendedTrendsByKind` which fetches broadly
 * and filters client-side — keeps the fetch path identical to the hub.
 */
export function useDiscoverKind(
  kind: string,
  limit = 50,
): UseDiscoverKindResult {
  const { getToken, isLoaded } = useAuth();
  const [trends, setTrends] = React.useState<FeedTrend[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await getRecommendedTrendsByKind(kind, { limit }, { token });
      setTrends(res.trends);
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load trend data."),
      );
      setTrends([]);
    } finally {
      setLoading(false);
    }
  }, [getToken, kind, limit]);

  React.useEffect(() => {
    if (isLoaded) void refresh();
  }, [isLoaded, refresh]);

  return { trends, loading, error, refresh };
}

export interface UseViralTemplatesResult {
  templates: TemplateSummary[];
  loading: boolean;
  error: string;
  refresh: () => Promise<void>;
}

/**
 * Fetch viral shot-templates standalone — used by the /discover/creators page
 * where we combine format-kind trends with the template gallery to give the
 * richest available proxy for rising creator formats.
 */
export function useViralTemplates(): UseViralTemplatesResult {
  const { getToken, isLoaded } = useAuth();
  const [templates, setTemplates] = React.useState<TemplateSummary[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = (await getToken()) ?? undefined;
      const res = await getViralTemplates({ token });
      setTemplates(res.templates);
    } catch (err) {
      setError(
        friendlyErrorMessage(err, "Failed to load templates."),
      );
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  React.useEffect(() => {
    if (isLoaded) void refresh();
  }, [isLoaded, refresh]);

  return { templates, loading, error, refresh };
}
