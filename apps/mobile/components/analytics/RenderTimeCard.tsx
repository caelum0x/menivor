/**
 * Compose-stage render-time distribution: p50 / p90 / average tiles (reusing the
 * shared StatCard) plus the sample count the percentiles were computed from.
 */

import { StyleSheet, Text, View } from "react-native";

import { StatCard } from "@/components/me/StatCard";
import { colors } from "@/components/me/theme";
import type { RenderTimeStats } from "@/lib/types";

import { formatCount, formatDuration } from "./format";

interface RenderTimeCardProps {
  stats: RenderTimeStats;
}

export function RenderTimeCard({ stats }: RenderTimeCardProps) {
  return (
    <View style={styles.wrap}>
      <View style={styles.grid}>
        <StatCard
          label="Median (p50)"
          value={formatDuration(stats.p50_ms)}
          accent={colors.success}
        />
        <StatCard
          label="p90"
          value={formatDuration(stats.p90_ms)}
          hint="9 in 10 render faster"
          accent={colors.accent}
        />
        <StatCard label="Average" value={formatDuration(stats.avg_ms)} />
        <StatCard
          label="Samples"
          value={formatCount(stats.count)}
          hint="Compose-stage renders"
        />
      </View>
      {stats.count === 0 ? (
        <Text style={styles.note}>
          No compose-stage renders in this window yet.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  note: { color: colors.muted, fontSize: 11 },
});
