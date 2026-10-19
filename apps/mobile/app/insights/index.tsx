/**
 * INSIGHTS — the caller's lifetime totals (GET /me/insights): reels made, jobs,
 * credits and spend, plus entry points to referral, presets and winning
 * templates. The trailing-window charts (funnel, spend, burn, render time,
 * breakdowns) live once, on the Creator Dashboard (/analytics), linked from the
 * top of this screen, so the two screens no longer fetch and draw the same
 * data. Everything is strictly per-user (session key sent as `x-api-key`).
 *
 * Nav manifest (for the integration agent to register in app/_layout.tsx):
 *   { route: "/insights",                   title: "Insights" }
 *   { route: "/insights/referral",          title: "Referral Program" }
 *   { route: "/insights/presets",           title: "Reel Presets" }
 *   { route: "/insights/winning-templates", title: "Winning Templates" }
 *   { route: "/insights/winners",           title: "Winners" }
 */

import { useCallback, useEffect, useState } from "react";
import type { ReactElement } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { Stack, useRouter } from "expo-router";

import { getInsights, isAbortError } from "@/lib/api";
import type { Insights } from "@/lib/types";
import { useSession } from "@/src/shared/auth";

import { Icon } from "@/components/ui/Icon";
import { Section } from "@/components/me/Section";
import { StatCard } from "@/components/me/StatCard";
import { describeError } from "@/components/me/errors";
import {
  formatCount,
  formatDuration,
  formatStateLabel,
  formatUsd,
} from "@/components/me/format";
import { colors } from "@/components/me/theme";

type LoadStatus = "loading" | "ready" | "error";

interface DashboardData {
  insights: Insights;
}

export default function InsightsDashboardScreen(): ReactElement {
  const { apiKey } = useSession();
  const token = apiKey ?? undefined;
  const router = useRouter();

  const [status, setStatus] = useState<LoadStatus>("loading");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (signal: AbortSignal, isRefresh: boolean): Promise<void> => {
      if (!isRefresh) setStatus("loading");
      setError("");
      try {
        const insights = await getInsights({ token, signal });
        if (signal.aborted) return;
        setData({ insights });
        setStatus("ready");
      } catch (err: unknown) {
        if (signal.aborted || isAbortError(err)) return;
        setError(describeError(err, "Failed to load your insights."));
        setStatus("error");
      } finally {
        if (!signal.aborted) setRefreshing(false);
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal, false);
    return () => controller.abort();
  }, [load]);

  const onRefresh = useCallback((): void => {
    setRefreshing(true);
    const controller = new AbortController();
    void load(controller.signal, true);
  }, [load]);

  return (
    <>
      <Stack.Screen options={{ title: "Insights", presentation: "card" }} />
      <ScrollView
        style={styles.container}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
          />
        }
      >
        <Text style={styles.pageTitle}>Your creator insights</Text>
        <Text style={styles.pageSub}>
          Lifetime totals across your reels, credits and spend. The Creator
          Dashboard has the day-by-day funnel, spend and render-time charts.
        </Text>

        <Pressable
          style={styles.dashboardLink}
          onPress={() => router.push("/analytics")}
          accessibilityRole="button"
        >
          <View style={styles.dashboardLinkBody}>
            <Text style={styles.dashboardLinkTitle}>Creator Dashboard</Text>
            <Text style={styles.dashboardLinkSub}>
              Funnel, spend over time, credit burn, render times and breakdowns
            </Text>
          </View>
          <Icon name="chevron-forward" size={20} color={colors.muted} />
        </Pressable>

        <Pressable
          style={styles.dashboardLink}
          onPress={() => router.push("/insights/winners")}
          accessibilityRole="button"
        >
          <Icon name="trophy-outline" size={20} color={colors.accent} />
          <View style={styles.dashboardLinkBody}>
            <Text style={styles.dashboardLinkTitle}>Winners and remake loop</Text>
            <Text style={styles.dashboardLinkSub}>
              Which hook variant won, why it won, and one tap to remake it
            </Text>
          </View>
          <Icon name="chevron-forward" size={20} color={colors.muted} />
        </Pressable>

        <View style={styles.linkRow}>
          <NavPill
            label="Referral"
            onPress={() => router.push("/insights/referral")}
          />
          <NavPill
            label="Presets"
            onPress={() => router.push("/insights/presets")}
          />
          <NavPill
            label="Winning Templates"
            onPress={() => router.push("/insights/winning-templates")}
          />
        </View>

        {status === "loading" ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.accent} size="large" />
          </View>
        ) : status === "error" ? (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{error}</Text>
            <Pressable style={styles.retry} onPress={onRefresh}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        ) : data ? (
          <Dashboard data={data} />
        ) : null}

        <View style={styles.spacer} />
      </ScrollView>
    </>
  );
}

interface DashboardProps {
  data: DashboardData;
}

function Dashboard({ data }: DashboardProps): ReactElement {
  const { insights } = data;
  const byState = Object.entries(insights.jobs_by_state ?? {});

  return (
    <View style={styles.dashboard}>
      <Section title="LIFETIME">
        <View style={styles.grid}>
          <StatCard
            label="Reels made"
            value={formatCount(insights.videos_generated)}
            hint="Successfully rendered"
            accent={colors.success}
          />
          <StatCard
            label="Jobs total"
            value={formatCount(insights.jobs_total)}
            hint="All create attempts"
            accent={colors.accent}
          />
          <StatCard
            label="Credits balance"
            value={formatCount(insights.credits_balance)}
            hint={`${formatCount(insights.credits_spent)} spent to date`}
          />
          <StatCard
            label="Total spend"
            value={formatUsd(insights.total_cost_usd)}
            hint="Cumulative render cost"
            accent={colors.primary}
          />
          <StatCard
            label="Avg render time"
            value={formatDuration(insights.avg_render_ms)}
            hint="Compose stage, per reel"
          />
          <StatCard
            label="Credits spent"
            value={formatCount(insights.credits_spent)}
            hint="Lifetime burn"
            accent={colors.error}
          />
        </View>
        {byState.length > 0 ? (
          <View style={styles.breakdown}>
            {byState.map(([state, count]) => (
              <View key={state} style={styles.breakdownRow}>
                <Text style={styles.breakdownLabel}>{formatStateLabel(state)}</Text>
                <Text style={styles.breakdownValue}>{formatCount(Number(count))}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </Section>

      <Text style={styles.footNote}>Pull down to refresh</Text>
    </View>
  );
}

interface NavPillProps {
  label: string;
  onPress: () => void;
}

function NavPill({ label, onPress }: NavPillProps): ReactElement {
  return (
    <Pressable style={styles.pill} onPress={onPress}>
      <Text style={styles.pillText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 20 },
  pageTitle: { color: colors.textPrimary, fontSize: 22, fontWeight: "800" },
  pageSub: { color: colors.muted, fontSize: 13, lineHeight: 18, marginTop: 4 },
  linkRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginTop: 16,
    marginBottom: 8,
  },
  pill: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    backgroundColor: colors.card,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  pillText: { color: colors.textSecondary, fontSize: 13, fontWeight: "700" },
  dashboard: { gap: 4, marginTop: 16 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  breakdown: {
    width: "100%",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
    marginTop: 12,
  },
  breakdownRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  breakdownLabel: { color: colors.textSecondary, fontSize: 14 },
  breakdownValue: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
  selectorRow: { gap: 10, marginBottom: 20, marginTop: 8 },
  windowLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1.2,
  },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: 80 },
  errorBox: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
    alignItems: "flex-start",
    marginTop: 20,
  },
  errorText: { color: colors.error, fontSize: 14 },
  retry: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  retryText: { color: colors.textSecondary, fontWeight: "600" },
  footNote: {
    color: colors.muted,
    fontSize: 12,
    textAlign: "center",
    marginTop: 4,
  },
  spacer: { height: 40 },
  dashboardLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.accent,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    marginTop: 16,
  },
  dashboardLinkBody: { flex: 1, gap: 4 },
  dashboardLinkTitle: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  dashboardLinkSub: { color: colors.muted, fontSize: 12 },
});
