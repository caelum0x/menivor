/**
 * INSIGHTS section of the Me tab. Fetches GET /me/insights and renders a grid
 * of stat cards derived from the caller-scoped {@link Insights} payload.
 */

import { useCallback } from "react";
import { StyleSheet, Text, View } from "react-native";

import { getInsights } from "@/lib/api";
import type { Insights } from "@/lib/types";

import { Section, SectionState } from "./Section";
import { StatCard } from "./StatCard";
import { formatCount, formatDuration, formatStateLabel, formatUsd } from "./format";
import { colors } from "./theme";
import { useResource } from "./use-resource";

interface InsightsSectionProps {
  token: string | undefined;
}

export function InsightsSection({ token }: InsightsSectionProps) {
  const fetcher = useCallback(() => getInsights({ token }), [token]);
  const { status, data, error, reload } = useResource<Insights>(fetcher);

  return (
    <Section title="INSIGHTS">
      <SectionState status={status} error={error} onRetry={reload}>
        {data ? <InsightsGrid insights={data} /> : null}
      </SectionState>
    </Section>
  );
}

function InsightsGrid({ insights }: { insights: Insights }) {
  const byState = Object.entries(insights.jobs_by_state ?? {});
  return (
    <View style={styles.grid}>
      <StatCard
        label="Jobs total"
        value={formatCount(insights.jobs_total)}
        accent={colors.accent}
      />
      <StatCard
        label="Videos generated"
        value={formatCount(insights.videos_generated)}
        hint="Successfully rendered reels"
        accent={colors.success}
      />
      <StatCard
        label="Credits balance"
        value={formatCount(insights.credits_balance)}
        hint={`${formatCount(insights.credits_spent)} spent to date`}
      />
      <StatCard
        label="Credits spent"
        value={formatCount(insights.credits_spent)}
        accent={colors.error}
      />
      <StatCard
        label="Total cost"
        value={formatUsd(insights.total_cost_usd)}
        hint="Cumulative render spend"
      />
      <StatCard
        label="Avg. render time"
        value={formatDuration(insights.avg_render_ms)}
        hint="Compose stage, per reel"
        accent={colors.accent}
      />
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
    </View>
  );
}

const styles = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  breakdown: {
    width: "100%",
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  breakdownRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  breakdownLabel: { color: colors.textSecondary, fontSize: 14 },
  breakdownValue: { color: colors.textPrimary, fontSize: 14, fontWeight: "700" },
});
