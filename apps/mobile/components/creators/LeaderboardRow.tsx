/**
 * One ranked creator in the leaderboard: rank badge, identity, the highlighted
 * value for the currently-selected metric, and a couple of secondary stats.
 * Tapping the row deep-links to the creator's public profile (via `onPress`).
 * Renders ONLY safe public fields from {@link LeaderboardEntry}.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { LeaderboardEntry, LeaderboardMetric } from "@/lib/types";
import { colors } from "@/components/me/theme";

import { creatorSubtitle, creatorTitle, formatCompact, formatRating } from "./format";
import { METRIC_LABELS } from "./LeaderboardMetricPicker";

interface LeaderboardRowProps {
  entry: LeaderboardEntry;
  metric: LeaderboardMetric;
  /** Called with the creator's addressing `user_id` for profile deep-linking. */
  onPress: (userId: string) => void;
}

/** The headline value shown for the active ranking metric. */
function metricValue(entry: LeaderboardEntry, metric: LeaderboardMetric): string {
  switch (metric) {
    case "followers":
      return formatCompact(entry.follower_count);
    case "clones":
      return formatCompact(entry.total_clones_received);
    case "rating":
      return formatRating(entry.avg_rating);
    case "published":
      return formatCompact(entry.published_template_count);
    case "win_score":
      return `${Math.round(entry.win_score)}`;
    case "reputation":
    default:
      return formatCompact(entry.reputation_score);
  }
}

export function LeaderboardRow({ entry, metric, onPress }: LeaderboardRowProps) {
  const subtitle = creatorSubtitle(entry);

  return (
    <Pressable
      style={styles.row}
      onPress={() => onPress(entry.user_id)}
      accessibilityRole="button"
      accessibilityLabel={`View ${creatorTitle(entry)}'s profile`}
    >
      <View style={styles.rankBox}>
        <Text style={styles.rank}>{entry.rank}</Text>
      </View>

      <View style={styles.identity}>
        <Text style={styles.title} numberOfLines={1}>
          {creatorTitle(entry)}
        </Text>
        {subtitle ? (
          <Text style={styles.subtitle} numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
        <Text style={styles.secondary} numberOfLines={1}>
          {formatCompact(entry.follower_count)} followers ·{" "}
          {formatCompact(entry.published_template_count)} published
        </Text>
      </View>

      <View style={styles.metricBox}>
        <Text style={styles.metricValue}>{metricValue(entry, metric)}</Text>
        <Text style={styles.metricLabel}>{METRIC_LABELS[metric]}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  rankBox: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.cardAlt,
    borderColor: colors.border,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  rank: { color: colors.accent, fontSize: 14, fontWeight: "800" },
  identity: { flex: 1, gap: 2 },
  title: { color: colors.textPrimary, fontSize: 15, fontWeight: "700" },
  subtitle: { color: colors.accent, fontSize: 12, fontWeight: "600" },
  secondary: { color: colors.muted, fontSize: 12 },
  metricBox: { alignItems: "flex-end", gap: 2, minWidth: 56 },
  metricValue: { color: colors.textPrimary, fontSize: 18, fontWeight: "800" },
  metricLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
});
