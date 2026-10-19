/**
 * A horizontal chip row for choosing the leaderboard ranking metric
 * (reputation | followers | clones | rating | published | win_score). Mirrors
 * the marketplace sort-chip pattern. Presentational + selection callback only;
 * the parent (`app/leaderboard.tsx`) owns the metric of record and the fetch.
 */

import { Pressable, ScrollView, StyleSheet, Text } from "react-native";

import { LEADERBOARD_METRICS, type LeaderboardMetric } from "@/lib/types";
import { colors } from "@/components/me/theme";

/** Human-readable labels for each ranking metric, in the union's order. */
export const METRIC_LABELS: Readonly<Record<LeaderboardMetric, string>> = {
  reputation: "Reputation",
  followers: "Followers",
  clones: "Clones",
  rating: "Rating",
  published: "Published",
  win_score: "Win score",
};

interface LeaderboardMetricPickerProps {
  metric: LeaderboardMetric;
  onChange: (metric: LeaderboardMetric) => void;
}

export function LeaderboardMetricPicker({
  metric,
  onChange,
}: LeaderboardMetricPickerProps) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {LEADERBOARD_METRICS.map((option) => {
        const active = option === metric;
        return (
          <Pressable
            key={option}
            style={[styles.chip, active && styles.chipActive]}
            onPress={() => onChange(option)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
          >
            <Text style={[styles.chipText, active && styles.chipTextActive]}>
              {METRIC_LABELS[option]}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: 8, paddingRight: 8 },
  chip: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { color: colors.textSecondary, fontSize: 13 },
  chipTextActive: { color: colors.textPrimary, fontWeight: "700" },
});
