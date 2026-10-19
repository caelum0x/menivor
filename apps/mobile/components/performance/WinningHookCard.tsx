/**
 * A single winning-hook aggregate: the hook line, its deterministic win_score,
 * and the supporting reel/view/engagement/retention stats. Purely
 * presentational. `rank` is the 1-based position in the ranked list.
 */

import { StyleSheet, Text, View } from "react-native";

import type { WinningHook } from "@/lib/types";

import { colors } from "@/components/me/theme";
import { formatCount } from "@/components/me/format";
import { formatPct, formatScore } from "./format";

interface WinningHookCardProps {
  hook: WinningHook;
  rank: number;
}

export function WinningHookCard({ hook, rank }: WinningHookCardProps) {
  const reels = Number.isFinite(hook.reels) ? hook.reels : 0;
  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.rank}>#{rank}</Text>
        <View style={styles.scorePill}>
          <Text style={styles.scoreValue}>{formatScore(hook.win_score)}</Text>
          <Text style={styles.scoreLabel}>win score</Text>
        </View>
      </View>

      <Text style={styles.hook} numberOfLines={3}>
        “{hook.hook || "Untitled hook"}”
      </Text>

      <View style={styles.stats}>
        <Stat label="Reels" value={formatCount(reels)} />
        <Stat label="Views" value={formatCount(hook.views)} />
        <Stat label="Engagements" value={formatCount(hook.engagements)} />
        <Stat label="Avg retention" value={formatPct(hook.avg_retention_pct)} />
      </View>
    </View>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 16,
    gap: 12,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  rank: { color: colors.muted, fontSize: 14, fontWeight: "800" },
  scorePill: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 6,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  scoreValue: { color: colors.accent, fontSize: 16, fontWeight: "800" },
  scoreLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "600",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  hook: {
    color: colors.textPrimary,
    fontSize: 15,
    fontWeight: "600",
    fontStyle: "italic",
    lineHeight: 21,
  },
  stats: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  stat: { flexBasis: "22%", flexGrow: 1, gap: 2 },
  statValue: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  statLabel: { color: colors.muted, fontSize: 11 },
});
