/**
 * A daily bar series rendered with plain RN Views (no chart lib). Each day is a
 * vertical bar whose height is proportional to the largest value in the window;
 * a sparse subset of day labels is shown on the axis to avoid crowding. Used
 * for cost-over-time and credit-burn-over-time.
 */

import { StyleSheet, Text, View } from "react-native";

import { colors } from "@/components/me/theme";
import type { AnalyticsPoint } from "@/lib/types";

import { formatDay, toPercent } from "./format";

interface TimeSeriesBarsProps {
  points: AnalyticsPoint[];
  /** Fill colour for the bars (defaults to accent). */
  color?: string;
  /** Formats a bucket value for the peak-day caption (e.g. USD or count). */
  formatValue: (value: number) => string;
  /** Caption noun for the peak day, e.g. "spend" or "burn". */
  peakLabel?: string;
  emptyLabel?: string;
}

const CHART_HEIGHT = 120;
/** Show at most this many axis labels, evenly spaced across the window. */
const MAX_AXIS_LABELS = 4;

export function TimeSeriesBars({
  points,
  color,
  formatValue,
  peakLabel = "peak",
  emptyLabel = "No activity in this window yet.",
}: TimeSeriesBarsProps) {
  if (points.length === 0) {
    return (
      <View style={styles.card}>
        <Text style={styles.empty}>{emptyLabel}</Text>
      </View>
    );
  }

  const max = points.reduce((acc, p) => Math.max(acc, p.value), 0);
  const peak = points.reduce(
    (acc, p) => (p.value > acc.value ? p : acc),
    points[0],
  );
  const labelStride = Math.max(1, Math.ceil(points.length / MAX_AXIS_LABELS));

  return (
    <View style={styles.card}>
      <View style={styles.chart}>
        {points.map((point, index) => {
          const heightPct = toPercent(point.value, max);
          return (
            <View key={`${point.date}-${index}`} style={styles.column}>
              <View style={styles.barArea}>
                <View
                  style={[
                    styles.bar,
                    {
                      height: max > 0 ? `${Math.max(heightPct, 1)}%` : 2,
                      backgroundColor: color ?? colors.accent,
                    },
                  ]}
                />
              </View>
              <Text style={styles.axisLabel} numberOfLines={1}>
                {index % labelStride === 0 ? formatDay(point.date) : ""}
              </Text>
            </View>
          );
        })}
      </View>
      <Text style={styles.caption}>
        {max > 0
          ? `${peakLabel === "peak" ? "Peak" : `Peak ${peakLabel}`}: ${formatValue(
              peak.value,
            )} on ${formatDay(peak.date)}`
          : "No activity in this window yet."}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    gap: 8,
  },
  chart: {
    flexDirection: "row",
    alignItems: "flex-end",
    height: CHART_HEIGHT,
    gap: 2,
  },
  column: { flex: 1, alignItems: "center", height: "100%" },
  barArea: {
    flex: 1,
    width: "100%",
    justifyContent: "flex-end",
    alignItems: "stretch",
  },
  bar: { width: "100%", borderRadius: 3, minHeight: 2 },
  axisLabel: {
    color: colors.muted,
    fontSize: 9,
    marginTop: 4,
    height: 12,
  },
  caption: { color: colors.muted, fontSize: 11 },
  empty: { color: colors.muted, fontSize: 13, paddingVertical: 12 },
});
