/**
 * Trends Feed — the durable, backend-scored feed of rising, not-yet-peaked
 * trends to build to. The default view is a pull-to-refresh list backed by the
 * REAL `GET /trends/recommended` feed; the header panel lets a creator score
 * their own candidate series (`POST /trends/rank`) and persist the winners into
 * the feed (`POST /trends/observe`). Every row deep-links to Compose (Group A).
 *
 * This replaces the old client-only `trend-lab` math with server-scored data.
 */

import * as React from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { useRouter } from "expo-router";

import { colors } from "@/components/me/theme";
import { isAbortError, makeAbortError } from "@/src/shared/api";
import { useSession } from "@/src/shared/auth";
import { getRecommendedTrends, type ObservedTrend } from "@/lib/trends";

import { RankPanel } from "./components/RankPanel";
import { TrendCard, type TrendCardData } from "./components/TrendCard";

const FEED_LIMIT = 30;

type Phase = "loading" | "ready" | "error";

export function TrendsFeedScreen() {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [trends, setTrends] = React.useState<ObservedTrend[]>([]);
  const [phase, setPhase] = React.useState<Phase>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const inFlight = React.useRef<AbortController | null>(null);

  const load = React.useCallback(
    async (mode: "initial" | "refresh") => {
      inFlight.current?.abort(makeAbortError());
      const controller = new AbortController();
      inFlight.current = controller;

      if (mode === "refresh") setRefreshing(true);
      else setPhase("loading");
      setError(null);

      try {
        const res = await getRecommendedTrends(FEED_LIMIT, {
          token,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setTrends(res.trends);
        setPhase("ready");
      } catch (err) {
        if (isAbortError(err) || controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Failed to load trends.");
        setPhase("error");
      } finally {
        if (inFlight.current === controller) inFlight.current = null;
        if (mode === "refresh") setRefreshing(false);
      }
    },
    [token],
  );

  React.useEffect(() => {
    void load("initial");
    return () => inFlight.current?.abort(makeAbortError());
  }, [load]);

  const onCompose = React.useCallback(
    (trend: TrendCardData) => {
      router.push({
        pathname: "/compose",
        params: {
          trend_id: trend.trend_id,
          subject: trend.label?.trim() ? trend.label : trend.trend_id,
        },
      });
    },
    [router],
  );

  const onForecast = React.useCallback(
    (trend: TrendCardData) => {
      if (!trend.id) return;
      router.push({
        pathname: "/diffusion-lab",
        params: {
          observation_id: String(trend.id),
          trend_id: trend.trend_id,
          subject: trend.label?.trim() ? trend.label : trend.trend_id,
        },
      });
    },
    [router],
  );

  const renderItem = React.useCallback(
    ({ item }: { item: ObservedTrend }) => (
      <TrendCard trend={item} onCompose={onCompose} onForecast={onForecast} />
    ),
    [onCompose, onForecast],
  );

  const header = (
    <View style={styles.header}>
      <Text style={styles.intro}>
        Rising, not-yet-peaked trends — scored by the pipeline, freshest
        opportunity first. Build before the peak.
      </Text>
      <RankPanel
        token={token}
        onObserved={() => void load("refresh")}
        onCompose={onCompose}
      />
      <View style={styles.divider} />
      <Text style={styles.feedTitle}>Recommended feed</Text>
    </View>
  );

  const empty = (() => {
    if (phase === "loading" && !refreshing) {
      return (
        <View style={styles.state}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.stateText}>Loading the trends feed…</Text>
        </View>
      );
    }
    if (phase === "error") {
      return (
        <View style={styles.state}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable
            style={styles.retry}
            accessibilityRole="button"
            onPress={() => void load("initial")}
            testID="feed-retry"
          >
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      );
    }
    return (
      <View style={styles.state}>
        <Text style={styles.stateText}>
          No trends in the feed yet. Score a candidate series above and tap
          "Save to feed" to seed it.
        </Text>
      </View>
    );
  })();

  return (
    <FlatList
      style={styles.container}
      contentContainerStyle={styles.content}
      data={trends}
      keyExtractor={(t) => String(t.id)}
      renderItem={renderItem}
      ListHeaderComponent={header}
      ListEmptyComponent={empty}
      ItemSeparatorComponent={() => <View style={styles.gap} />}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void load("refresh")}
          tintColor={colors.primary}
        />
      }
      testID="trends-feed-list"
    />
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  header: {
    gap: 12,
    marginBottom: 12,
  },
  intro: {
    color: colors.textSecondary,
    fontSize: 14,
    lineHeight: 20,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginTop: 4,
  },
  feedTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: "800",
  },
  gap: {
    height: 12,
  },
  state: {
    alignItems: "center",
    gap: 12,
    paddingVertical: 32,
  },
  stateText: {
    color: colors.textSecondary,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 20,
  },
  errorText: {
    color: colors.error,
    fontSize: 14,
    textAlign: "center",
  },
  retry: {
    borderColor: colors.primary,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 20,
    paddingVertical: 10,
  },
  retryText: {
    color: colors.primary,
    fontSize: 14,
    fontWeight: "700",
  },
});
